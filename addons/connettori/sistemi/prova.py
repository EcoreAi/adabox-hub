"""La prova di HubSpot: risponde con il suo formato, senza uscire in rete. Il connettore passa dallo stesso codice,
cambia solo il trasporto. I record (persone, aziende, opportunità) stanno in RecordProva, con le loro associazioni,
così si vede cosa arriva dall'altra parte.

Qui stanno anche gli aiuti comuni alle prove degli altri sistemi (prova_salesforce, prova_zoho): ognuna offre
`trasporto`, `simula_nuovo`, `simula_modifica` e `riga`."""
import datetime
import json
import re
import secrets

import httpx2 as httpx
from django.utils import timezone

from ..models import RecordProva
from .base import AZIENDE, OPPORTUNITA, PERSONE
from .hubspot import OGGETTI

CONTATTI = PERSONE
FASI = [  # la pipeline predefinita di HubSpot, con gli stessi id
    ("appointmentscheduled", "Appointment scheduled", 0, "0.2", "false"),
    ("qualifiedtobuy", "Qualified to buy", 1, "0.4", "false"),
    ("presentationscheduled", "Presentation scheduled", 2, "0.6", "false"),
    ("decisionmakerboughtin", "Decision maker bought-in", 3, "0.8", "false"),
    ("contractsent", "Contract sent", 4, "0.9", "false"),
    ("closedwon", "Closed won", 5, "1.0", "true"),
    ("closedlost", "Closed lost", 6, "0.0", "true"),
]


# --- aiuti comuni a tutte le prove --------------------------------------------------------------------------------

def adesso_ms():
    return int(timezone.now().timestamp() * 1000)


def scrivi(collegamento, proprieta, id_esterno=None, tipo=CONTATTI):
    """Un record creato o cambiato dall'altra parte."""
    id_esterno = id_esterno or str(secrets.randbelow(10**10))
    r, _ = RecordProva.objects.get_or_create(collegamento=collegamento, tipo=tipo, id_esterno=id_esterno,
                                             defaults={"proprieta": {}, "modificato_ms": 0})
    r.proprieta, r.modificato_ms = {**r.proprieta, **proprieta}, adesso_ms()
    r.save()
    return r


def associa(collegamento, da, a):
    """Associa due RecordProva nei due versi (come fa HubSpot)."""
    for x, y in ((da, a), (a, da)):
        voci = x.associazioni.get(y.tipo, [])
        if y.id_esterno not in voci:
            x.associazioni = {**x.associazioni, y.tipo: voci + [y.id_esterno]}
            RecordProva.objects.filter(pk=x.pk).update(associazioni=x.associazioni)


def prossima_fase(fasi, attuale, vinta):
    """La fase dopo `attuale`, senza andare oltre quella vinta."""
    return fasi[min(fasi.index(attuale) + 1 if attuale in fasi else 0, fasi.index(vinta))]


# --- HubSpot --------------------------------------------------------------------------------------------------------

def _iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _forma(r):
    return {"id": r.id_esterno, "properties": {**r.proprieta, OGGETTI[r.tipo]["modificato"]: _iso(r.modificato_ms)}}


def _cerca(qs, corpo, tipo):
    filtro = corpo["filterGroups"][0]["filters"][0]
    campo, valore = filtro["propertyName"], filtro["value"]
    if campo == OGGETTI[tipo]["modificato"]:
        voci = list(qs.filter(modificato_ms__gte=int(valore)).order_by("modificato_ms", "pk"))
    else:
        voci = [r for r in qs.order_by("pk") if str(r.proprieta.get(campo) or "").lower() == str(valore).lower()]
    inizio = int(corpo.get("after") or 0)
    pagina = voci[inizio:inizio + corpo["limit"]]
    dati = {"results": [_forma(r) for r in pagina]}
    if inizio + corpo["limit"] < len(voci):
        dati["paging"] = {"next": {"after": str(inizio + corpo["limit"])}}
    return dati


def trasporto(collegamento):
    def rispondi(richiesta):
        percorso = richiesta.url.path
        tutti = RecordProva.objects.filter(collegamento=collegamento)
        if percorso == "/crm/v3/pipelines/deals":
            return httpx.Response(200, json={"results": [{"id": "default", "label": "Sales Pipeline", "stages": [
                {"id": i, "label": e, "displayOrder": o, "metadata": {"probability": p, "isClosed": c}} for i, e, o, p, c in FASI]}]})
        if m := re.fullmatch(r"/crm/v4/associations/(\w+)/(\w+)/batch/read", percorso):
            da, a = m.groups()
            ids = [v["id"] for v in json.loads(richiesta.content)["inputs"]]
            risultati = [{"from": {"id": r.id_esterno}, "to": [{"toObjectId": int(x), "associationTypes": []} for x in r.associazioni.get(a, [])]}
                         for r in tutti.filter(tipo=da, id_esterno__in=ids) if r.associazioni.get(a)]
            return httpx.Response(200, json={"status": "COMPLETE", "results": risultati})
        if m := re.fullmatch(r"/crm/v4/objects/(\w+)/(\w+)/associations/default/(\w+)/(\w+)", percorso):
            da, id_da, a, id_a = m.groups()
            x, y = tutti.filter(tipo=da, id_esterno=id_da).first(), tutti.filter(tipo=a, id_esterno=id_a).first()
            if x is None or y is None:
                return httpx.Response(404, json={"message": "resource not found"})
            associa(collegamento, x, y)
            return httpx.Response(200, json={"status": "COMPLETE", "results": []})
        if m := re.fullmatch(r"/crm/v3/objects/(\w+)/search", percorso):
            if m.group(1) not in OGGETTI:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json=_cerca(tutti.filter(tipo=m.group(1)), json.loads(richiesta.content), m.group(1)))
        if (m := re.fullmatch(r"/crm/v3/objects/(\w+)", percorso)) and m.group(1) in OGGETTI:
            if richiesta.method == "GET":
                return httpx.Response(200, json={"results": []})
            return httpx.Response(201, json=_forma(scrivi(collegamento, json.loads(richiesta.content)["properties"], tipo=m.group(1))))
        if (m := re.fullmatch(r"/crm/v3/objects/(\w+)/(\w+)", percorso)) and m.group(1) in OGGETTI:
            tipo, id_est = m.groups()
            if not tutti.filter(tipo=tipo, id_esterno=id_est).exists():
                return httpx.Response(404, json={"message": "resource not found"})
            return httpx.Response(200, json=_forma(scrivi(collegamento, json.loads(richiesta.content)["properties"], id_est, tipo)))
        return httpx.Response(404, json={"message": "not found"})
    return httpx.MockTransport(rispondi)


def simula_nuovo(c, s):
    """Una persona nuova e, se il collegamento le comprende, la sua azienda e un'opportunità (s: i dati scelti)."""
    persona = scrivi(c, {"firstname": s["nome"], "lastname": s["cognome"], "email": s["email"], "phone": s["telefono"]})
    azienda = None
    if c.aziende:
        azienda = scrivi(c, {"name": s["ditta"], "domain": s["dominio"], "city": "Milano"}, tipo=AZIENDE)
        associa(c, persona, azienda)
    if c.opportunita:
        fase = FASI[s["fase"] % 5]
        trattativa = scrivi(c, {"dealname": s["titolo"], "amount": str(s["importo"]), "pipeline": "default", "dealstage": fase[0]}, tipo=OPPORTUNITA)
        associa(c, trattativa, azienda or persona)


def simula_modifica(c, ruolo):
    record = RecordProva.objects.filter(collegamento=c, tipo=CONTATTI).first()
    if record is None:
        return False
    scrivi(c, {"jobtitle": ruolo}, record.id_esterno)
    trattativa = RecordProva.objects.filter(collegamento=c, tipo=OPPORTUNITA).first()
    if trattativa is not None:
        fase = prossima_fase([f[0] for f in FASI], trattativa.proprieta.get("dealstage"), "closedwon")
        scrivi(c, {"dealstage": fase}, trattativa.id_esterno, OPPORTUNITA)
    return True


def riga(r):
    """(nome, dettagli) di un record del sistema finto, per la pagina del collegamento."""
    p = r.proprieta
    if r.tipo == AZIENDE:
        return p.get("name", ""), f"{p.get('domain', '')} {p.get('city', '')}"
    if r.tipo == OPPORTUNITA:
        return p.get("dealname", ""), f"{p.get('amount', '')} € · {p.get('dealstage', '')}"
    return f"{p.get('firstname', '')} {p.get('lastname', '')}", f"{p.get('email', '')} {p.get('phone', '')} {p.get('jobtitle', '')}"
