"""Pagina della settimana: griglia compiti × giorni per registrare le proprie ore in un colpo solo."""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from progetti.models import Compito, progetti_visibili

from .models import RigaOre

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
    if request.method == "POST":
        errori = _salva(request, compiti, giorni, somme)
        if not errori:
            messages.success(request, "Ore della settimana salvate.")
            return redirect(f"{request.path}?data={lunedi.isoformat()}")
        for e in errori:
            messages.error(request, e)
    righe = [{"compito": c, "celle": [{"nome": f"ore_{c.pk}_{g.isoformat()}",
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


def _salva(request, compiti, giorni, somme):
    """Per ogni cella cambiata: le righe dell'utente per quel compito e giorno diventano una sola riga."""
    nuovi, errori = {}, []
    for c in compiti:
        for g in giorni:
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
