"""Pagina della settimana: griglia compiti × giorni per registrare le proprie ore in un colpo solo."""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core import parametri
from progetti.models import Compito, progetti_visibili

from .models import Cronometro, RigaOre
from .segnali import cronometro_fermato

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def _lunedi(testo):
    try:
        giorno = datetime.date.fromisoformat(testo)
    except (TypeError, ValueError):
        giorno = timezone.localdate()
    return giorno - datetime.timedelta(days=giorno.weekday())


def _compiti(user, giorni):
    """I compiti aperti assegnati all'utente nei progetti attivi che vede, più quelli con ore in settimana."""
    progetti = progetti_visibili(user).filter(stato="attivo").values("pk")
    con_ore = RigaOre.objects.filter(utente=user, data__in=giorni).exclude(compito=None).values("compito")
    return (Compito.objects.filter(progetto__in=progetti)
            .filter(Q(assegnatari=user, fase__chiusa=False) | Q(pk__in=con_ore))
            .select_related("progetto").distinct().order_by("progetto__nome", "titolo"))


@login_required
@permission_required("timesheet.add_rigaore", raise_exception=True)
def settimana(request):
    lunedi = _lunedi(request.GET.get("data") or request.POST.get("data"))
    giorni = [lunedi + datetime.timedelta(days=i) for i in range(7)]
    compiti = list(_compiti(request.user, giorni))
    somme = {(r["compito"], r["data"]): r["t"] for r in RigaOre.objects.filter(
        utente=request.user, data__in=giorni, compito__in=compiti).values("compito", "data").annotate(t=Sum("ore"))}
    chiuse = set(RigaOre.objects.filter(utente=request.user, data__in=giorni, compito__in=compiti)
                 .filter(Q(approvata=True) | Q(bloccata=True)).values_list("compito", "data"))
    if request.method == "POST":
        errori = _salva(request, compiti, giorni, somme, chiuse)
        if not errori:
            messages.success(request, "Ore della settimana salvate.")
            return redirect(f"{request.path}?data={lunedi.isoformat()}")
        for e in errori:
            messages.error(request, e)
    righe = [{"compito": c, "celle": [{"nome": f"ore_{c.pk}_{g.isoformat()}",
                                       "chiusa": (c.pk, g) in chiuse,
                                       "valore": request.POST.get(f"ore_{c.pk}_{g.isoformat()}") if request.method == "POST"
                                       else (somme.get((c.pk, g)) or ""), "giorno": g} for g in giorni],
              "totale": sum((somme.get((c.pk, g)) or 0) for g in giorni)} for c in compiti]
    per_giorno = RigaOre.objects.filter(utente=request.user, data__in=giorni).values("data").annotate(t=Sum("ore"))
    totali = {r["data"]: r["t"] for r in per_giorno}
    return render(request, "timesheet/settimana.html", {
        "righe": righe, "giorni": [(GIORNI[i], g, totali.get(g, 0)) for i, g in enumerate(giorni)],
        "lunedi": lunedi, "precedente": lunedi - datetime.timedelta(days=7),
        "successivo": lunedi + datetime.timedelta(days=7), "totale": sum(totali.values()),
    })


def _salva(request, compiti, giorni, somme, chiuse=frozenset()):
    """Per ogni cella cambiata: le righe dell'utente per quel compito e giorno diventano una sola riga.
    Le celle con ore approvate o fatturate non si toccano."""
    nuovi, errori = {}, []
    for c in compiti:
        for g in giorni:
            if (c.pk, g) in chiuse:
                continue
            testo = request.POST.get(f"ore_{c.pk}_{g.isoformat()}", "").strip().replace(",", ".")
            try:
                valore = Decimal(testo) if testo else Decimal(0)
            except InvalidOperation:
                errori.append(f"{c.titolo}, {g:%d/%m}: «{testo}» non è un numero di ore.")
                continue
            if not 0 <= valore <= 24:
                errori.append(f"{c.titolo}, {g:%d/%m}: le ore vanno da 0 a 24.")
                continue
            if valore != (somme.get((c.pk, g)) or 0):
                nuovi[(c, g)] = valore
    for g in giorni:
        fuori = (RigaOre.objects.filter(utente=request.user, data=g).exclude(compito__in=[c for c, d in nuovi if d == g])
                 .aggregate(t=Sum("ore"))["t"] or 0)
        if fuori + sum(v for (c, d), v in nuovi.items() if d == g) > 24:
            errori.append(f"Le ore del {g:%d/%m} superano 24.")
    if errori:
        return errori
    with transaction.atomic():
        for (c, g), valore in nuovi.items():
            RigaOre.objects.filter(utente=request.user, compito=c, data=g).delete()
            if valore:
                RigaOre.objects.create(azienda=c.azienda, utente=request.user, progetto=c.progetto, compito=c,
                                       data=g, ore=valore, descrizione="Dalla settimana")
    return []


def _torna(request):
    prossima = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(prossima, {request.get_host()}, request.is_secure()):
        return redirect(prossima)
    return redirect(reverse("timesheet:ore_lista"))


@login_required
@permission_required("timesheet.add_rigaore", raise_exception=True)
@require_POST
def cronometro_avvia(request):
    """Avvia il cronometro; se ne girava un altro, prima lo ferma e salva le sue ore."""
    from progetti.models import Progetto
    progetto = get_object_or_404(progetti_visibili(request.user, Progetto.objects.filter(azienda=request.azienda, stato="attivo")),
                                 pk=request.POST.get("progetto") or 0)
    compito = None
    if request.POST.get("compito"):
        compito = get_object_or_404(Compito, pk=request.POST["compito"], progetto=progetto)
    corrente = Cronometro.objects.filter(utente=request.user).first()
    if corrente:
        _ferma(request, corrente)
    ticket = request.POST.get("ticket", "")
    Cronometro.objects.update_or_create(utente=request.user, defaults={
        "azienda": progetto.azienda, "progetto": progetto, "compito": compito, "avviato": timezone.now(),
        "ticket_id_origine": int(ticket) if ticket.isdigit() else None,
        "descrizione": request.POST.get("descrizione", "")[:250]})
    return _torna(request)


def _arrotonda(secondi, azienda):
    """In ore, per eccesso al multiplo scelto dall'azienda (timesheet.arrotonda_minuti, 0 = al minuto)."""
    minuti = Decimal(max(secondi, 1)) / 60
    passo = Decimal(parametri.leggi("timesheet.arrotonda_minuti", azienda) or 1)
    multipli = (minuti / passo).to_integral_value(rounding="ROUND_CEILING")
    return min((multipli * passo / 60).quantize(Decimal("0.01")), Decimal(24))


def _ferma(request, cronometro):
    riga = RigaOre(azienda=cronometro.azienda, utente=cronometro.utente, progetto=cronometro.progetto,
                   compito=cronometro.compito, data=timezone.localtime(cronometro.avviato).date(),
                   descrizione=cronometro.descrizione or "Dal cronometro",
                   ore=_arrotonda((timezone.now() - cronometro.avviato).total_seconds(), cronometro.azienda))
    try:
        riga.clean()
    except ValidationError as e:
        messages.error(request, f"Ore non salvate: {' '.join(e.messages)} Inseriscile a mano.")
        cronometro.delete()
        return None
    with transaction.atomic():
        riga.save()
        ticket = cronometro.ticket_id_origine
        cronometro.delete()
        cronometro_fermato.send(sender=RigaOre, riga=riga, ticket_id=ticket)
    messages.success(request, f"Registrate {riga.ore} ore su {riga.progetto}.")
    return riga


@login_required
@permission_required("timesheet.add_rigaore", raise_exception=True)
@require_POST
def cronometro_ferma(request):
    corrente = Cronometro.objects.filter(utente=request.user).first()
    if corrente:
        _ferma(request, corrente)
    return _torna(request)
