"""Consegne, carico, Gantt e simulazione: tutte letture del piano, che si ricalcola a ogni richiesta."""
import datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import render
from django.utils import timezone

from core.dashboard import queryset
from progetti.models import Compito, Milestone, Progetto

from . import piano as motore

SETTIMANE_GANTT = 16


def _visibili(request):
    return set(queryset(request, Compito).values_list("pk", flat=True))


def scheda_progetto(piano, progetto):
    voci = piano.di_progetto(progetto.pk)
    senza = [v for v in piano.senza_data if v.progetto_id == progetto.pk]
    dati = motore.consegna(piano, voci, senza, progetto.fine)
    dati.update(progetto=progetto, avanzamento=motore.avanzamento(progetto.azienda, progetto_pk=progetto.pk))
    return dati


@login_required
@permission_required("capacita.view_capacita", raise_exception=True)
def consegne(request):
    piano = motore.calcola(request.azienda, timezone.localdate())
    visibili = _visibili(request)
    schede = []
    for progetto in queryset(request, Progetto).filter(stato=Progetto.ATTIVO).select_related("cliente", "azienda"):
        scheda = scheda_progetto(piano, progetto)
        if not (scheda["compiti"] or scheda["senza_data"]):
            continue
        scheda["milestone"] = []
        for m in Milestone.objects.filter(progetto=progetto).order_by("scadenza", "pk"):
            voci = [v for v in piano.di_progetto(progetto.pk) if v.milestone_id == m.pk]
            if voci:
                scheda["milestone"].append({"nome": m.nome, **motore.consegna(piano, voci, [], m.scadenza)})
        scheda["da_sistemare"] = [v for v in piano.senza_data if v.progetto_id == progetto.pk and v.pk in visibili]
        scheda["ritardi"] = [v for v in piano.di_progetto(progetto.pk) if v.in_ritardo and v.pk in visibili]
        schede.append(scheda)
    schede.sort(key=lambda s: (-s["ritardo"], s["prevista"] or datetime.date.max))
    return render(request, "capacita/consegne.html", {
        "schede": schede, "in_ritardo": sum(1 for s in schede if s["ritardo"]), "in_tempo": sum(1 for s in schede if not s["ritardo"]),
        "compiti_tardi": sum(s["in_ritardo"] for s in schede), "senza_data": sum(s["senza_data"] for s in schede)})


@login_required
@permission_required("capacita.view_capacita", raise_exception=True)
def carico(request):
    piano = motore.calcola(request.azienda, timezone.localdate())
    dati = motore.carico(piano)
    visibili = _visibili(request)
    for riga in dati["righe"]:
        for cella in riga["celle"]:
            cella["compiti"] = ", ".join(titolo for pk, titolo in cella["titoli"] if pk in visibili)[:300]
    return render(request, "capacita/carico.html", dati)


@login_required
@permission_required("capacita.view_capacita", raise_exception=True)
def gantt(request):
    oggi = timezone.localdate()
    piano = motore.calcola(request.azienda, oggi)
    visibili = _visibili(request)
    inizio = oggi - datetime.timedelta(days=oggi.weekday())
    durata = SETTIMANE_GANTT * 7
    fine = inizio + datetime.timedelta(days=durata)
    utenti = {u.pk: u.get_full_name() or u.get_username() for u in get_user_model().objects.all()}
    gruppi = []
    for progetto in queryset(request, Progetto).filter(stato=Progetto.ATTIVO).order_by("nome"):
        righe = []
        for v in sorted(piano.di_progetto(progetto.pk), key=lambda v: (v.inizio, v.fine)):
            if v.pk not in visibili or v.inizio >= fine:
                continue
            da, a = (v.inizio - inizio).days, min((v.fine - inizio).days + 1, durata)
            righe.append({"voce": v, "sinistra": da * 100 / durata, "larghezza": (a - da) * 100 / durata, "oltre": v.fine >= fine,
                          "persone": ", ".join(utenti.get(p, "") for p in v.persone)})
        if righe:
            gruppi.append({"progetto": progetto, "righe": righe})
    settimane = [{"lunedi": inizio + datetime.timedelta(weeks=i), "sinistra": i * 7 * 100 / durata} for i in range(SETTIMANE_GANTT)]
    return render(request, "capacita/gantt.html", {"gruppi": gruppi, "settimane": settimane, "larghezza_settimana": 100 / SETTIMANE_GANTT,
                                                   "oggi_sinistra": (oggi - inizio).days * 100 / durata})


def _persone(request, piano):
    pk = set(piano.calendario.schede)
    for v in piano.voci:
        pk.update(v.persone)
    return get_user_model().objects.filter(pk__in=pk, is_active=True).order_by("first_name", "username")


@login_required
@permission_required("capacita.view_capacita", raise_exception=True)
def simula(request):
    """«E se arrivasse questo lavoro?»: la data che avrebbe e chi slitterebbe. Non salva nulla."""
    oggi = timezone.localdate()
    base = motore.calcola(request.azienda, oggi)
    progetti = queryset(request, Progetto).filter(stato=Progetto.ATTIVO).order_by("nome")
    persone = _persone(request, base)
    contesto = {"progetti": progetti, "persone": persone, "dati": request.GET}
    if request.GET.get("ore"):
        progetto = progetti.filter(pk=request.GET.get("progetto") or 0).first() if str(request.GET.get("progetto", "")).isdigit() else None
        utente = persone.filter(pk=request.GET.get("persona")).first() if str(request.GET.get("persona", "")).isdigit() else None
        try:
            ore = Decimal(request.GET["ore"].replace(",", "."))
            valide = ore.is_finite() and 0 < ore <= 5000
        except InvalidOperation:
            valide = False
        if not (progetto and utente and valide):
            contesto["errore"] = "Scegli progetto e persona e indica le ore, fino a 5000."
        else:
            ipotesi = motore.Voce(None, "Il lavoro nuovo", progetto.pk, [utente.pk], ore, alta=request.GET.get("priorita") == "alta")
            dopo = motore.calcola(request.azienda, oggi, ipotesi)
            prima_fine = base.per_compito()
            visibili = _visibili(request)
            slittano = []
            for v in dopo.voci:
                vecchia = prima_fine.get(v.pk)
                if v.pk in visibili and vecchia and vecchia.fine and v.fine > vecchia.fine:
                    slittano.append({"voce": v, "prima": vecchia.fine, "giorni": (v.fine - vecchia.fine).days,
                                     "nuovo_ritardo": v.in_ritardo and not vecchia.in_ritardo})
            slittano.sort(key=lambda s: -s["giorni"])
            contesto["esito"] = {"voce": ipotesi, "progetto": progetto, "utente": utente, "slittano": slittano[:30], "totale": len(slittano),
                                 "nuovi_ritardi": sum(1 for s in slittano if s["nuovo_ritardo"])}
    return render(request, "capacita/simula.html", contesto)
