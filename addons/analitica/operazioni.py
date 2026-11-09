"""Imputare le righe alle voci (anche ripartite), report per asse, consuntivo e confronto con il budget."""
import datetime
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import fonti
from .models import Imputazione, RigaBudget

CENT = Decimal("0.01")


def _gia(fonte, ids, asse, escludi_voce=None):
    """{id_riga: percentuale già imputata sull'asse}."""
    qs = Imputazione.objects.filter(tipo_riga=fonte.tipo(), id_riga__in=ids, voce__asse=asse)
    if escludi_voce is not None:
        qs = qs.exclude(voce=escludi_voce)
    somme = {}
    for i in qs:
        somme[i.id_riga] = somme.get(i.id_riga, Decimal(0)) + i.percentuale
    return somme


@transaction.atomic
def imputa(azienda, fonte, ids, voce, percentuale=Decimal(100), sostituisci=True):
    """Le righe sulla voce. Con sostituisci, le imputazioni della riga sullo stesso asse si rifanno; altrimenti si
    aggiunge una parte (la somma sull'asse non supera il 100%). Restituisce quante righe."""
    percentuale = Decimal(percentuale)
    if not 0 < percentuale <= 100:
        raise ValidationError("La percentuale va da 0 a 100.")
    if voce.azienda_id != azienda.pk:
        raise ValidationError("La voce è di un'altra azienda.")
    righe = list(fonte.righe(azienda, ids=ids).values_list("pk", flat=True)) if ids else []
    if not righe:
        raise ValidationError("Scegli almeno una riga.")
    tipo = fonte.tipo()
    if sostituisci:
        Imputazione.objects.filter(tipo_riga=tipo, id_riga__in=righe, voce__asse=voce.asse).delete()
    else:
        gia = _gia(fonte, righe, voce.asse, escludi_voce=voce)
        oltre = [pk for pk in righe if gia.get(pk, 0) + percentuale > 100]
        if oltre:
            raise ValidationError(f"Su {len(oltre)} righe si supererebbe il 100% per l'asse {voce.asse}.")
        Imputazione.objects.filter(tipo_riga=tipo, id_riga__in=righe, voce=voce).delete()
    Imputazione.objects.bulk_create(Imputazione(azienda=azienda, voce=voce, tipo_riga=tipo, id_riga=pk, percentuale=percentuale)
                                    for pk in righe)
    return len(righe)


@transaction.atomic
def applica_modello(azienda, fonte, ids, modello):
    righe_modello = modello.controlla()
    righe = list(fonte.righe(azienda, ids=ids).values_list("pk", flat=True)) if ids else []
    if not righe:
        raise ValidationError("Scegli almeno una riga.")
    tipo, asse = fonte.tipo(), righe_modello[0].voce.asse
    Imputazione.objects.filter(tipo_riga=tipo, id_riga__in=righe, voce__asse=asse).delete()
    Imputazione.objects.bulk_create(Imputazione(azienda=azienda, voce=rm.voce, tipo_riga=tipo, id_riga=pk, percentuale=rm.percentuale)
                                    for pk in righe for rm in righe_modello)
    return len(righe)


def togli(azienda, fonte, ids, asse):
    return Imputazione.objects.filter(azienda=azienda, tipo_riga=fonte.tipo(), id_riga__in=ids, voce__asse=asse).delete()[0]


def imputazioni_di(fonte, righe):
    """{id_riga: [Imputazione]} per mostrare le righe di un documento."""
    mappa = {}
    for i in Imputazione.objects.filter(tipo_riga=fonte.tipo(), id_riga__in=[r.pk for r in righe]).select_related("voce__asse"):
        mappa.setdefault(i.id_riga, []).append(i)
    return mappa


def movimenti(azienda, voci, dal=None, al=None):
    """[{voce, fonte, riga, importo}] delle imputazioni sulle voci nel periodo (importo già in percentuale e con segno)."""
    risultato = []
    imputazioni = list(Imputazione.objects.filter(azienda=azienda, voce__in=voci).select_related("voce"))
    for fonte in fonti.disponibili():
        tipo = fonte.tipo()
        mie = [i for i in imputazioni if i.tipo_riga_id == tipo.pk]
        if not mie:
            continue
        righe = {r.pk: r for r in fonte.righe(azienda, dal, al, ids=[i.id_riga for i in mie])}
        for i in mie:
            r = righe.get(i.id_riga)
            if r is not None:
                risultato.append({"voce": i.voce, "fonte": fonte, "riga": r,
                                  "importo": (fonte.importo(r) * i.percentuale / 100).quantize(CENT)})
    return risultato


def report(azienda, asse, dal=None, al=None):
    """Per voce dell'asse: ricavi, costi esterni, note spese, margine; più il non imputato per fonte."""
    voci = list(asse.voci.all())
    per_voce = {v.pk: {"voce": v, "ricavi": Decimal(0), "acquisti": Decimal(0), "spese": Decimal(0)} for v in voci}
    for m in movimenti(azienda, voci, dal, al):
        per_voce[m["voce"].pk][m["fonte"].categoria] += m["importo"]
    for x in per_voce.values():
        x["margine"] = x["ricavi"] + x["acquisti"] + x["spese"]
    non_imputato = []
    for fonte in fonti.disponibili():
        tipo = fonte.tipo()
        coperte = {}
        for i in Imputazione.objects.filter(azienda=azienda, tipo_riga=tipo, voce__asse=asse):
            coperte[i.id_riga] = coperte.get(i.id_riga, Decimal(0)) + i.percentuale
        resto = Decimal(0)
        for r in fonte.righe(azienda, dal, al):
            quota = max(Decimal(100) - coperte.get(r.pk, Decimal(0)), Decimal(0))
            if quota:
                resto += (fonte.importo(r) * quota / 100).quantize(CENT)
        non_imputato.append({"fonte": fonte, "importo": resto})
    righe = [x for x in per_voce.values() if x["ricavi"] or x["acquisti"] or x["spese"] or x["voce"].attiva]
    totale = {k: sum((x[k] for x in righe), Decimal(0)) for k in ("ricavi", "acquisti", "spese", "margine")}
    return {"righe": righe, "totale": totale, "non_imputato": non_imputato}


def costo_ore(voce, dal, al):
    """Il costo delle ore registrate sul progetto della voce, con i costi orari delle Commesse, se ci sono."""
    if not voce.progetto_id or not apps.is_installed("commesse"):
        return Decimal(0)
    from commesse.operazioni import _costi, _costo
    from timesheet.models import RigaOre
    costi = _costi(voce.azienda)
    qs = RigaOre.objects.filter(progetto_id=voce.progetto_id)
    if dal:
        qs = qs.filter(data__gte=dal)
    if al:
        qs = qs.filter(data__lte=al)
    return sum((r.ore * _costo(costi, r.utente_id, r.data) for r in qs), Decimal(0)).quantize(CENT)


def consuntivo(voce, dal, al):
    """{categoria: importo} positivo per la voce nel periodo: ricavi, costi esterni, spese, ore."""
    valori = {RigaBudget.RICAVI: Decimal(0), RigaBudget.ACQUISTI: Decimal(0), RigaBudget.SPESE: Decimal(0)}
    for m in movimenti(voce.azienda, [voce], dal, al):
        valori[m["fonte"].categoria] += m["importo"]
    valori = {k: abs(v) if k != RigaBudget.RICAVI else v for k, v in valori.items()}
    valori[RigaBudget.ORE] = costo_ore(voce, dal, al)
    return valori


def confronto(budget, oggi=None):
    """Per categoria: previsto, consuntivo, percentuale e proiezione a fine periodo (al ritmo di finora)."""
    oggi = oggi or timezone.localdate()
    fatto = consuntivo(budget.voce, budget.dal, min(budget.al, oggi))
    giorni = (budget.al - budget.dal).days + 1
    trascorsi = min(max((oggi - budget.dal).days + 1, 0), giorni)
    previsto = {}
    for r in budget.righe.all():
        previsto[r.categoria] = previsto.get(r.categoria, Decimal(0)) + r.importo
    righe = []
    for codice, nome in RigaBudget.CATEGORIE:
        p, c = previsto.get(codice, Decimal(0)), fatto.get(codice, Decimal(0))
        if not p and not c:
            continue
        proiezione = (c * giorni / trascorsi).quantize(CENT) if trascorsi else Decimal(0)
        righe.append({"categoria": codice, "nome": nome, "previsto": p, "consuntivo": c,
                      "percentuale": int(c * 100 / p) if p else None, "proiezione": proiezione,
                      "oltre": codice != RigaBudget.RICAVI and p and proiezione > p})
    ricavi = lambda chiave: sum((r[chiave] for r in righe if r["categoria"] == RigaBudget.RICAVI), Decimal(0))  # noqa: E731
    costi = lambda chiave: sum((r[chiave] for r in righe if r["categoria"] != RigaBudget.RICAVI), Decimal(0))  # noqa: E731
    return {"righe": righe, "margine_previsto": ricavi("previsto") - costi("previsto"),
            "margine_consuntivo": ricavi("consuntivo") - costi("consuntivo"),
            "margine_proiezione": ricavi("proiezione") - costi("proiezione"),
            "avanzamento": int(trascorsi * 100 / giorni) if giorni else 100}
