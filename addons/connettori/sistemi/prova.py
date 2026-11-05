"""La prova: risponde come HubSpot, con il suo formato, senza uscire in rete. Il connettore passa dallo stesso codice,
cambia solo il trasporto. I record stanno in RecordProva, così si vede cosa arriva dall'altra parte."""
import datetime
import json
import re
import secrets

import httpx2 as httpx
from django.utils import timezone

from ..models import RecordProva


def _adesso_ms():
    return int(timezone.now().timestamp() * 1000)


def _forma(r):
    return {"id": r.id_esterno, "properties": {**r.proprieta, "lastmodifieddate": _iso(r.modificato_ms)}}


def _iso(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def scrivi(collegamento, proprieta, id_esterno=None):
    """Un record creato o cambiato dall'altra parte."""
    id_esterno = id_esterno or str(secrets.randbelow(10**10))
    r, _ = RecordProva.objects.get_or_create(collegamento=collegamento, id_esterno=id_esterno, defaults={"proprieta": {}, "modificato_ms": 0})
    r.proprieta, r.modificato_ms = {**r.proprieta, **proprieta}, _adesso_ms()
    r.save()
    return r


def trasporto(collegamento):
    def rispondi(richiesta):
        percorso = richiesta.url.path
        qs = RecordProva.objects.filter(collegamento=collegamento)
        if percorso == "/crm/v3/objects/contacts/search":
            corpo = json.loads(richiesta.content)
            filtro = corpo["filterGroups"][0]["filters"][0]
            if filtro["propertyName"] == "email":
                voci = [r for r in qs if (r.proprieta.get("email") or "").lower() == filtro["value"].lower()]
            else:
                voci = list(qs.filter(modificato_ms__gte=int(filtro["value"])).order_by("modificato_ms", "pk"))
            inizio = int(corpo.get("after") or 0)
            pagina = voci[inizio:inizio + corpo["limit"]]
            dati = {"results": [_forma(r) for r in pagina]}
            if inizio + corpo["limit"] < len(voci):
                dati["paging"] = {"next": {"after": str(inizio + corpo["limit"])}}
            return httpx.Response(200, json=dati)
        if percorso == "/crm/v3/objects/contacts":
            if richiesta.method == "GET":
                return httpx.Response(200, json={"results": []})
            return httpx.Response(201, json=_forma(scrivi(collegamento, json.loads(richiesta.content)["properties"])))
        if m := re.fullmatch(r"/crm/v3/objects/contacts/(\w+)", percorso):
            if not qs.filter(id_esterno=m.group(1)).exists():
                return httpx.Response(404, json={"message": "resource not found"})
            return httpx.Response(200, json=_forma(scrivi(collegamento, json.loads(richiesta.content)["properties"], m.group(1))))
        return httpx.Response(404, json={"message": "not found"})
    return httpx.MockTransport(rispondi)
