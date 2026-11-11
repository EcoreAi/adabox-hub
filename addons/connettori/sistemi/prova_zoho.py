"""La prova di Zoho CRM: un account finto nel data center eu che risponde nel formato v8 (refresh token, record con
If-Modified-Since e pagine, ricerca con «equals» che in realtà contiene, risposte {"data": [...]}, 204 quando non
c'è nulla), senza uscire in rete. Le fasi hanno solo le chiavi certe del picklist (niente probabilità): così si prova
anche il caso peggiore. I record stanno in RecordProva con i nomi dei campi di Zoho; i lookup sono {"id", "name"}."""
import datetime
import json
import re
import secrets

import httpx2 as httpx

from ..models import RecordProva
from .base import AZIENDE, OPPORTUNITA, PERSONE
from .prova import prossima_fase, scrivi

CENTRO = "eu"
ACCOUNTS, API = "accounts.zoho.eu", "www.zohoapis.eu"
TOKEN = "prova-zoho"
TIPI = {"Contacts": PERSONE, "Accounts": AZIENDE, "Deals": OPPORTUNITA}
OBBLIGATORI = {PERSONE: ["Last_Name"], AZIENDE: ["Account_Name"], OPPORTUNITA: ["Deal_Name", "Stage"]}
FASI = ["Qualification", "Needs Analysis", "Value Proposition", "Identify Decision Makers", "Proposal/Price Quote", "Negotiation/Review",
        "Closed Won", "Closed Lost", "Closed-Lost to Competition"]
LOOKUP = {"Account_Name": AZIENDE, "Contact_Name": PERSONE}


def nuovo_id():
    return str(10**18 + secrets.randbelow(10**18))


def _quando(ms):
    return datetime.datetime.fromtimestamp(ms // 1000, tz=datetime.timezone.utc).isoformat()


def _forma(r, campi=None):
    voce = {"id": r.id_esterno, "Modified_Time": _quando(r.modificato_ms)}
    for campo in campi or r.proprieta:
        if campo not in voce:
            voce[campo] = r.proprieta.get(campo)
    return voce


def _esito(stato, codice, messaggio, dettagli=None, esito="error"):
    return httpx.Response(stato, json={"data": [{"code": codice, "details": dettagli or {}, "message": messaggio, "status": esito}]})


def _con_nomi(tutti, tipo, corpo):
    """I lookup scritti come {"id"} diventano {"id", "name"}, come li restituisce Zoho."""
    for campo, verso in LOOKUP.items():
        if tipo == AZIENDE and campo == "Account_Name":
            continue
        if isinstance(corpo.get(campo), dict):
            altro = tutti.filter(tipo=verso, id_esterno=str(corpo[campo].get("id"))).first()
            if altro is None:
                return None, campo
            nome = altro.proprieta.get("Account_Name") if verso == AZIENDE else f"{altro.proprieta.get('First_Name') or ''} {altro.proprieta.get('Last_Name') or ''}"
            corpo[campo] = {"id": altro.id_esterno, "name": str(nome).strip()}
    return corpo, None


def trasporto(collegamento):
    def rispondi(richiesta):
        host, percorso, tutti = richiesta.url.host, richiesta.url.path, RecordProva.objects.filter(collegamento=collegamento)
        if host == ACCOUNTS and percorso == "/oauth/v2/token":
            return httpx.Response(200, json={"access_token": TOKEN, "api_domain": f"https://{API}", "token_type": "Bearer", "expires_in": 3600})
        if host != API:
            return httpx.Response(404)
        if richiesta.headers.get("Authorization") != f"Zoho-oauthtoken {TOKEN}":
            return httpx.Response(401, json={"code": "INVALID_TOKEN", "details": {}, "message": "invalid oauth token", "status": "error"})
        parametri = richiesta.url.params
        if percorso == "/crm/v8/settings/fields":
            if parametri.get("module") != "Deals":
                return httpx.Response(200, json={"fields": []})
            valori = [{"display_value": "-None-", "actual_value": "-None-", "sequence_number": 0, "id": "0", "type": "used"}]
            valori += [{"display_value": f, "actual_value": f, "sequence_number": i + 1, "id": str(i + 1), "type": "used"} for i, f in enumerate(FASI)]
            return httpx.Response(200, json={"fields": [{"api_name": "Deal_Name", "data_type": "text"},
                                                        {"api_name": "Stage", "data_type": "picklist", "pick_list_values": valori}]})
        if (m := re.fullmatch(r"/crm/v8/(\w+)/search", percorso)) and m.group(1) in TIPI:
            c = re.fullmatch(r"\((\w+):equals:(.*)\)", parametri.get("criteria", ""))
            if c is None:
                return httpx.Response(400, json={"code": "INVALID_QUERY", "details": {}, "message": "invalid query", "status": "error"})
            campo, valore = c.group(1), re.sub(r"\\(.)", r"\1", c.group(2)).lower()
            voci = [_forma(r, [campo]) for r in tutti.filter(tipo=TIPI[m.group(1)]).order_by("pk") if valore in str(r.proprieta.get(campo) or "").lower()]
            return httpx.Response(200, json={"data": voci, "info": {"count": len(voci), "more_records": False}}) if voci else httpx.Response(204)
        if (m := re.fullmatch(r"/crm/v8/(\w+)", percorso)) and m.group(1) in TIPI:
            tipo = TIPI[m.group(1)]
            if richiesta.method == "GET":
                if not parametri.get("fields"):
                    return httpx.Response(400, json={"code": "REQUIRED_PARAM_MISSING", "details": {"param": "fields"}, "message": "fields", "status": "error"})
                voci = tutti.filter(tipo=tipo).order_by("modificato_ms", "pk")
                if desde := richiesta.headers.get("If-Modified-Since"):
                    ms = int(datetime.datetime.fromisoformat(desde).timestamp() * 1000)
                    voci = voci.filter(modificato_ms__gte=ms)
                per_pagina, pagina = int(parametri.get("per_page", 200)), int(parametri.get("page", 1))
                voci = list(voci)
                parte = voci[(pagina - 1) * per_pagina:pagina * per_pagina]
                if not parte:
                    return httpx.Response(204)
                altri = pagina * per_pagina < len(voci)
                return httpx.Response(200, json={"data": [_forma(r, parametri["fields"].split(",")) for r in parte],
                                                 "info": {"per_page": per_pagina, "count": len(parte), "page": pagina, "more_records": altri,
                                                          "next_page_token": None}})
            corpo = (json.loads(richiesta.content).get("data") or [{}])[0]
            mancano = [c for c in OBBLIGATORI[tipo] if not corpo.get(c)]
            if mancano:
                return _esito(400, "MANDATORY_NOT_FOUND", "required field not found", {"api_name": mancano[0]})
            corpo, sbagliato = _con_nomi(tutti, tipo, corpo)
            if corpo is None:
                return _esito(400, "INVALID_DATA", "the related id given seems to be invalid", {"api_name": sbagliato})
            r = scrivi(collegamento, corpo, nuovo_id(), tipo)
            return _esito(201, "SUCCESS", "record added", {"id": r.id_esterno}, esito="success")
        if (m := re.fullmatch(r"/crm/v8/(\w+)/(\d+)", percorso)) and m.group(1) in TIPI and richiesta.method == "PUT":
            tipo, id_est = TIPI[m.group(1)], m.group(2)
            if not tutti.filter(tipo=tipo, id_esterno=id_est).exists():
                return _esito(400, "INVALID_DATA", "the id given seems to be invalid", {"api_name": "id"})
            corpo, sbagliato = _con_nomi(tutti, tipo, (json.loads(richiesta.content).get("data") or [{}])[0])
            if corpo is None:
                return _esito(400, "INVALID_DATA", "the related id given seems to be invalid", {"api_name": sbagliato})
            scrivi(collegamento, corpo, id_est, tipo)
            return _esito(200, "SUCCESS", "record updated", {"id": id_est}, esito="success")
        return httpx.Response(404, json={"code": "INVALID_URL_PATTERN", "details": {}, "message": "Please check if the URL trying to access is a correct one",
                                         "status": "error"})
    return httpx.MockTransport(rispondi)


def simula_nuovo(c, s):
    azienda = None
    if c.aziende:
        azienda = scrivi(c, {"Account_Name": s["ditta"], "Website": f"https://{s['dominio']}", "Billing_City": "Milano"}, nuovo_id(), AZIENDE)
    lookup = {"Account_Name": {"id": azienda.id_esterno, "name": s["ditta"]}} if azienda else {}
    persona = scrivi(c, {"First_Name": s["nome"], "Last_Name": s["cognome"], "Email": s["email"], "Phone": s["telefono"], **lookup}, nuovo_id())
    if c.opportunita:
        scrivi(c, {"Deal_Name": s["titolo"], "Amount": s["importo"], "Stage": FASI[s["fase"] % 6], **lookup,
                   "Contact_Name": {"id": persona.id_esterno, "name": f"{s['nome']} {s['cognome']}"}}, nuovo_id(), OPPORTUNITA)


def simula_modifica(c, ruolo):
    record = RecordProva.objects.filter(collegamento=c, tipo=PERSONE).first()
    if record is None:
        return False
    scrivi(c, {"Title": ruolo}, record.id_esterno)
    trattativa = RecordProva.objects.filter(collegamento=c, tipo=OPPORTUNITA).first()
    if trattativa is not None:
        scrivi(c, {"Stage": prossima_fase(FASI, trattativa.proprieta.get("Stage"), "Closed Won")}, trattativa.id_esterno, OPPORTUNITA)
    return True


def riga(r):
    p = r.proprieta
    if r.tipo == AZIENDE:
        return p.get("Account_Name", ""), f"{p.get('Website') or ''} {p.get('Billing_City') or ''}"
    if r.tipo == OPPORTUNITA:
        return p.get("Deal_Name", ""), f"{p.get('Amount') or ''} € · {p.get('Stage') or ''}"
    return f"{p.get('First_Name') or ''} {p.get('Last_Name') or ''}", f"{p.get('Email') or ''} {p.get('Phone') or ''} {p.get('Title') or ''}"
