"""Risultati della vendita: per persona e per team, obiettivo e raggiunto, vinte e perse, tasso di vittoria, durata
media dalla creazione alla chiusura, pipeline aperta ponderata e motivi di perdita."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Count

from .models import ObiettivoVendita, Opportunita, TeamVendita


def _misura(qs):
    vinte = [o for o in qs if o.stato == Opportunita.VINTA]
    perse = [o for o in qs if o.stato == Opportunita.PERSA]
    chiuse = vinte + perse
    durate = [(o.chiusa_il - o.creata_il).days for o in chiuse if o.chiusa_il and o.creata_il]
    return {"vinto": sum((o.valore_atteso for o in vinte), Decimal(0)), "vinte": len(vinte), "perse": len(perse),
            "tasso": int(len(vinte) * 100 / len(chiuse)) if chiuse else None,
            "durata": round(sum(durate) / len(durate)) if durate else None}


def _obiettivo(qs, dal, al):
    """La somma degli obiettivi che cadono nel periodo (in proporzione ai giorni in comune)."""
    totale, numero = Decimal(0), 0
    for o in qs.filter(dal__lte=al, al__gte=dal):
        giorni = (o.al - o.dal).days + 1
        comuni = (min(o.al, al) - max(o.dal, dal)).days + 1
        totale += (o.importo * comuni / giorni).quantize(Decimal("0.01"))
        numero += round((o.numero or 0) * comuni / giorni)
    return totale, numero


def risultati(azienda, dal, al):
    chiuse = list(Opportunita.objects.filter(azienda=azienda, stato__in=[Opportunita.VINTA, Opportunita.PERSA],
                                             chiusa_il__gte=dal, chiusa_il__lte=al).select_related("commerciale", "team"))
    aperte = list(Opportunita.objects.filter(azienda=azienda, stato=Opportunita.APERTA).select_related("commerciale", "team"))
    persone = {}
    for o in chiuse + aperte:
        if o.commerciale_id:
            persone.setdefault(o.commerciale_id, o.commerciale)
    for ob in ObiettivoVendita.objects.filter(azienda=azienda, utente__isnull=False, dal__lte=al, al__gte=dal).select_related("utente"):
        persone.setdefault(ob.utente_id, ob.utente)
    righe_persone = []
    for uid, utente in persone.items():
        m = _misura([o for o in chiuse if o.commerciale_id == uid])
        obiettivo, numero = _obiettivo(ObiettivoVendita.objects.filter(azienda=azienda, utente_id=uid), dal, al)
        pipeline = sum((o.valore_atteso * o.probabilita / 100 for o in aperte if o.commerciale_id == uid), Decimal(0))
        righe_persone.append({"chi": utente, **m, "obiettivo": obiettivo, "numero_obiettivo": numero, "pipeline": pipeline.quantize(Decimal("0.01")),
                              "raggiunto": int(m["vinto"] * 100 / obiettivo) if obiettivo else None})
    righe_team = []
    for t in TeamVendita.objects.filter(azienda=azienda, attivo=True).prefetch_related("membri"):
        membri = {u.pk for u in t.membri.all()}
        sue = [o for o in chiuse if o.team_id == t.pk or (o.team_id is None and o.commerciale_id in membri)]
        m = _misura(sue)
        obiettivo, numero = _obiettivo(ObiettivoVendita.objects.filter(azienda=azienda, team=t), dal, al)
        righe_team.append({"chi": t, **m, "obiettivo": obiettivo, "numero_obiettivo": numero,
                           "raggiunto": int(m["vinto"] * 100 / obiettivo) if obiettivo else None})
    motivi = (Opportunita.objects.filter(azienda=azienda, stato=Opportunita.PERSA, chiusa_il__gte=dal, chiusa_il__lte=al)
              .values("motivo_perdita__nome").annotate(n=Count("pk")).order_by("-n"))
    return {"persone": sorted(righe_persone, key=lambda r: -r["vinto"]), "team": righe_team, "totale": _misura(chiuse),
            "motivi": [{"motivo": m["motivo_perdita__nome"] or "Senza motivo", "n": m["n"]} for m in motivi]}


@transaction.atomic
def riassegna_nel_team(opportunita, team):
    """Le opportunità ai membri del team, una alla volta a chi ha meno opportunità aperte. Restituisce {utente: n}."""
    membri = list(team.membri.filter(is_active=True))
    if not membri:
        return {}
    carico = {u.pk: Opportunita.objects.filter(commerciale=u, stato=Opportunita.APERTA).count() for u in membri}
    dati = {}
    for o in opportunita:
        scelto = min(membri, key=lambda u: (carico[u.pk], u.pk))
        if o.commerciale_id != scelto.pk:
            carico[scelto.pk] += 1
            if o.commerciale_id in carico and o.stato == Opportunita.APERTA:
                carico[o.commerciale_id] -= 1
        o.commerciale, o.team = scelto, team
        o.save(update_fields=["commerciale", "team"])
        dati[scelto] = dati.get(scelto, 0) + 1
    return dati
