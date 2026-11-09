"""Turni: la settimana per persona, con le assenze approvate e le ore rispetto al contratto; copia dalla settimana prima."""
import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from core.dashboard import queryset

from .models import AssegnazioneTurno, Assenza, Dipendente, TurnoLavoro

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def lunedi(testo=None):
    try:
        d = datetime.date.fromisoformat(testo) if testo else timezone.localdate()
    except ValueError:
        d = timezone.localdate()
    return d - datetime.timedelta(days=d.weekday())


def settimana(azienda, inizio, dipendenti):
    giorni = [inizio + datetime.timedelta(days=i) for i in range(7)]
    assegnati = {(a.dipendente_id, a.data): a for a in AssegnazioneTurno.objects.filter(
        azienda=azienda, data__range=(giorni[0], giorni[-1]), dipendente__in=dipendenti).select_related("turno")}
    assenze = {}
    for a in Assenza.objects.filter(dipendente__in=dipendenti, stato=Assenza.APPROVATA, dal__lte=giorni[-1], al__gte=giorni[0]).select_related("tipo"):
        for g in giorni:
            if a.dal <= g <= a.al:
                assenze[(a.dipendente_id, g)] = a
    righe = []
    for d in dipendenti:
        celle, ore = [], Decimal(0)
        for g in giorni:
            a = assegnati.get((d.pk, g))
            ore += a.turno.ore if a else 0
            celle.append({"data": g, "assegnato": a, "assenza": assenze.get((d.pk, g)), "conflitto": bool(a and assenze.get((d.pk, g)))})
        righe.append({"d": d, "celle": celle, "ore": ore.quantize(Decimal("0.1")), "contratto": d.ore_settimanali,
                      "oltre": ore > d.ore_settimanali})
    return giorni, righe


@login_required
@permission_required("personale.change_assegnazioneturno", raise_exception=True)
def griglia(request):
    inizio = lunedi(request.GET.get("settimana") or request.POST.get("settimana"))
    dipendenti = list(queryset(request, Dipendente).filter(attivo=True).order_by("cognome", "nome"))
    if request.GET.get("reparto", "").isdigit():
        dipendenti = [d for d in dipendenti if str(d.reparto_id) == request.GET["reparto"]]
    turni = list(queryset(request, TurnoLavoro).filter(attivo=True))
    if request.method == "POST":
        if request.POST.get("azione") == "copia":
            n = copia_settimana(request.azienda, inizio - datetime.timedelta(days=7), inizio)
            messages.success(request, f"Copiati {n} turni dalla settimana prima (i giorni già pieni restano).")
        else:
            salva(request, inizio, dipendenti, turni)
            messages.success(request, "Turni salvati.")
        return redirect(f"{request.path}?settimana={inizio.isoformat()}")
    giorni, righe = settimana(request.azienda, inizio, dipendenti)
    return render(request, "personale/turni.html", {
        "giorni": [(g, GIORNI[g.weekday()]) for g in giorni], "righe": righe, "turni": turni, "inizio": inizio,
        "prima": (inizio - datetime.timedelta(days=7)).isoformat(), "dopo": (inizio + datetime.timedelta(days=7)).isoformat()})


@transaction.atomic
def salva(request, inizio, dipendenti, turni):
    per_pk = {str(t.pk): t for t in turni}
    for d in dipendenti:
        for i in range(7):
            g = inizio + datetime.timedelta(days=i)
            valore = request.POST.get(f"t_{d.pk}_{g.isoformat()}")
            if valore is None:
                continue
            if valore in per_pk:
                AssegnazioneTurno.objects.update_or_create(dipendente=d, data=g, defaults={"azienda": d.azienda, "turno": per_pk[valore]})
            else:
                AssegnazioneTurno.objects.filter(dipendente=d, data=g).delete()


@transaction.atomic
def copia_settimana(azienda, da, a):
    n = 0
    for x in AssegnazioneTurno.objects.filter(azienda=azienda, data__range=(da, da + datetime.timedelta(days=6))):
        nuovo = x.data + (a - da)
        _, creato = AssegnazioneTurno.objects.get_or_create(dipendente_id=x.dipendente_id, data=nuovo,
                                                           defaults={"azienda": azienda, "turno_id": x.turno_id, "nota": x.nota})
        n += creato
    return n


def miei(dipendente, giorni=14):
    oggi = timezone.localdate()
    return list(dipendente.turni.filter(data__gte=oggi, data__lte=oggi + datetime.timedelta(days=giorni)).select_related("turno"))
