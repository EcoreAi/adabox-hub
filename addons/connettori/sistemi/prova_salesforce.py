"""La prova di Salesforce: un'organizzazione finta che risponde nel formato della REST API (token «client
credentials», SOQL con nextRecordsUrl, sobjects, errori come lista), senza uscire in rete. Capisce solo le
interrogazioni che fa il connettore. I record stanno in RecordProva con i nomi dei campi di Salesforce; i ruoli
delle persone sulle opportunità (OpportunityContactRole) sono le associazioni del record."""
import base64
import datetime
import json
import re
import secrets
import string

import httpx2 as httpx

from ..models import RecordProva
from .base import AZIENDE, OPPORTUNITA, PERSONE
from .prova import adesso_ms, associa, prossima_fase, scrivi
from .salesforce import VERSIONE

DOMINIO = "prova.my.salesforce.com"
TOKEN = "prova-sf"
TIPI = {"Contact": PERSONE, "Account": AZIENDE, "Opportunity": OPPORTUNITA}
PREFISSI = {PERSONE: "003", AZIENDE: "001", OPPORTUNITA: "006"}
OBBLIGATORI = {PERSONE: ["LastName"], AZIENDE: ["Name"], OPPORTUNITA: ["Name", "StageName", "CloseDate"]}
FASI = [  # le fasi standard di Salesforce: (etichetta, probabilità, chiusa, vinta)
    ("Prospecting", 10, False, False), ("Qualification", 10, False, False), ("Needs Analysis", 20, False, False),
    ("Value Proposition", 50, False, False), ("Proposal/Price Quote", 75, False, False), ("Negotiation/Review", 90, False, False),
    ("Closed Won", 100, True, True), ("Closed Lost", 0, True, False),
]
LETTERALE = r"'((?:[^'\\]|\\.)*)'"


def nuovo_id(tipo):
    return PREFISSI.get(tipo, "00K") + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(15))


def _letterale(testo):
    return re.sub(r"\\(.)", r"\1", testo)


def _modstamp(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}+0000"


def _forma(r, campi=None):
    oggetto = next(o for o, t in TIPI.items() if t == r.tipo)
    voce = {"attributes": {"type": oggetto, "url": f"/services/data/{VERSIONE}/sobjects/{oggetto}/{r.id_esterno}"},
            "Id": r.id_esterno, "SystemModstamp": _modstamp(r.modificato_ms)}
    for campo in campi or r.proprieta:
        if campo not in voce:
            voce[campo] = r.proprieta.get(campo)
    return voce


def _errore(stato, codice, messaggio, campi=None):
    return httpx.Response(stato, json=[{"message": messaggio, "errorCode": codice, "fields": campi or []}])


def _risultati(voci, pagina, inizio, soql):
    fine = inizio + pagina
    dati = {"totalSize": len(voci), "done": fine >= len(voci), "records": voci[inizio:fine]}
    if not dati["done"]:
        chiave = base64.urlsafe_b64encode(soql.encode()).decode().rstrip("=")
        dati["nextRecordsUrl"] = f"/services/data/{VERSIONE}/query/prova-{chiave}-{fine}"
    return dati


def _interroga(tutti, soql):
    """I record per le sole forme di SOQL usate dal connettore."""
    if m := re.fullmatch(r"SELECT (.+) FROM (\w+) WHERE SystemModstamp >= (\S+) ORDER BY SystemModstamp ASC", soql):
        campi, oggetto, quando = m.group(1).split(", "), m.group(2), m.group(3)
        ms = int(datetime.datetime.strptime(quando, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
        return [_forma(r, campi) for r in tutti.filter(tipo=TIPI[oggetto], modificato_ms__gte=ms).order_by("modificato_ms", "pk")]
    if m := re.fullmatch(r"SELECT Id FROM (\w+) LIMIT 1", soql):
        return [_forma(r, ["Id"]) for r in tutti.filter(tipo=TIPI[m.group(1)])[:1]]
    if m := re.fullmatch(rf"SELECT Id FROM (\w+) WHERE (\w+) = {LETTERALE} LIMIT 2", soql):
        oggetto, campo, valore = m.group(1), m.group(2), _letterale(m.group(3))
        return [_forma(r, ["Id"]) for r in tutti.filter(tipo=TIPI[oggetto]).order_by("pk")
                if str(r.proprieta.get(campo) or "").lower() == valore.lower()][:2]
    if m := re.fullmatch(rf"SELECT Id, Website FROM Account WHERE Website LIKE {LETTERALE} LIMIT 20", soql):
        parte = _letterale(m.group(1)).strip("%").lower()
        return [_forma(r, ["Id", "Website"]) for r in tutti.filter(tipo=AZIENDE).order_by("pk") if parte in str(r.proprieta.get("Website") or "").lower()][:20]
    if m := re.fullmatch(r"SELECT (.+) FROM OpportunityContactRole WHERE OpportunityId (?:IN \((.+)\)|= ('.+'))( ORDER BY IsPrimary DESC)?", soql):
        ids = [_letterale(x) for x in re.findall(LETTERALE, m.group(2) or m.group(3))]
        return [{"attributes": {"type": "OpportunityContactRole"}, "OpportunityId": r.id_esterno, "ContactId": c, "IsPrimary": i == 0}
                for r in tutti.filter(tipo=OPPORTUNITA, id_esterno__in=ids).order_by("pk") for i, c in enumerate(r.associazioni.get(PERSONE, []))]
    if m := re.fullmatch(r"SELECT (.+) FROM OpportunityStage WHERE IsActive = true ORDER BY SortOrder", soql):
        return [{"attributes": {"type": "OpportunityStage"}, "ApiName": e, "MasterLabel": e, "DefaultProbability": p, "IsClosed": c, "IsWon": v,
                 "SortOrder": i + 1, "IsActive": True} for i, (e, p, c, v) in enumerate(FASI)]
    return None


def trasporto(collegamento):
    def rispondi(richiesta):
        percorso, tutti = richiesta.url.path, RecordProva.objects.filter(collegamento=collegamento)
        if richiesta.url.host != DOMINIO:
            return httpx.Response(404)
        if percorso == "/services/oauth2/token":
            return httpx.Response(200, json={"access_token": TOKEN, "instance_url": f"https://{DOMINIO}", "token_type": "Bearer",
                                             "id": f"https://login.salesforce.com/id/00D/005", "issued_at": str(adesso_ms())})
        if richiesta.headers.get("Authorization") != f"Bearer {TOKEN}":
            return _errore(401, "INVALID_SESSION_ID", "Session expired or invalid")
        opzioni = re.search(r"batchSize=(\d+)", richiesta.headers.get("Sforce-Query-Options", ""))
        pagina = int(opzioni.group(1)) if opzioni else 2000
        if percorso == f"/services/data/{VERSIONE}/query":
            soql = richiesta.url.params.get("q", "")
            voci = _interroga(tutti, soql)
            if voci is None:
                return _errore(400, "MALFORMED_QUERY", f"La prova non capisce: {soql[:80]}")
            return httpx.Response(200, json=_risultati(voci, pagina, 0, soql))
        if m := re.fullmatch(rf"/services/data/{VERSIONE}/query/prova-([\w-]+)-(\d+)", percorso):
            chiave = m.group(1) + "=" * (-len(m.group(1)) % 4)
            soql = base64.urlsafe_b64decode(chiave).decode()
            return httpx.Response(200, json=_risultati(_interroga(tutti, soql), pagina, int(m.group(2)), soql))
        if m := re.fullmatch(rf"/services/data/{VERSIONE}/sobjects/(\w+)/", percorso):
            oggetto, corpo = m.group(1), json.loads(richiesta.content)
            if oggetto == "OpportunityContactRole":
                x = tutti.filter(tipo=OPPORTUNITA, id_esterno=corpo.get("OpportunityId")).first()
                y = tutti.filter(tipo=PERSONE, id_esterno=corpo.get("ContactId")).first()
                if x is None or y is None:
                    return _errore(400, "INVALID_CROSS_REFERENCE_KEY", "invalid cross reference id")
                associa(collegamento, x, y)
                return httpx.Response(201, json={"id": nuovo_id(None), "success": True, "errors": []})
            if oggetto not in TIPI:
                return _errore(404, "NOT_FOUND", "The requested resource does not exist")
            mancano = [c for c in OBBLIGATORI[TIPI[oggetto]] if not corpo.get(c)]
            if mancano:
                return _errore(400, "REQUIRED_FIELD_MISSING", f"Required fields are missing: [{', '.join(mancano)}]", mancano)
            r = scrivi(collegamento, corpo, nuovo_id(TIPI[oggetto]), TIPI[oggetto])
            return httpx.Response(201, json={"id": r.id_esterno, "success": True, "errors": []})
        if (m := re.fullmatch(rf"/services/data/{VERSIONE}/sobjects/(\w+)/(\w+)", percorso)) and richiesta.method == "PATCH":
            oggetto, id_est = m.groups()
            if oggetto not in TIPI or not tutti.filter(tipo=TIPI[oggetto], id_esterno=id_est).exists():
                return _errore(404, "NOT_FOUND", "The requested resource does not exist")
            scrivi(collegamento, json.loads(richiesta.content), id_est, TIPI[oggetto])
            return httpx.Response(204)
        return _errore(404, "NOT_FOUND", "The requested resource does not exist")
    return httpx.MockTransport(rispondi)


def simula_nuovo(c, s):
    persona = scrivi(c, {"FirstName": s["nome"], "LastName": s["cognome"], "Email": s["email"], "Phone": s["telefono"]}, nuovo_id(PERSONE))
    azienda = None
    if c.aziende:
        azienda = scrivi(c, {"Name": s["ditta"], "Website": f"https://{s['dominio']}", "BillingCity": "Milano"}, nuovo_id(AZIENDE), AZIENDE)
        scrivi(c, {"AccountId": azienda.id_esterno}, persona.id_esterno)
    if c.opportunita:
        fase = FASI[s["fase"] % 6][0]
        trattativa = scrivi(c, {"Name": s["titolo"], "Amount": s["importo"], "StageName": fase, "CloseDate": None,
                                "AccountId": azienda.id_esterno if azienda else None}, nuovo_id(OPPORTUNITA), OPPORTUNITA)
        associa(c, trattativa, persona)


def simula_modifica(c, ruolo):
    record = RecordProva.objects.filter(collegamento=c, tipo=PERSONE).first()
    if record is None:
        return False
    scrivi(c, {"Title": ruolo}, record.id_esterno)
    trattativa = RecordProva.objects.filter(collegamento=c, tipo=OPPORTUNITA).first()
    if trattativa is not None:
        fase = prossima_fase([f[0] for f in FASI], trattativa.proprieta.get("StageName"), "Closed Won")
        scrivi(c, {"StageName": fase}, trattativa.id_esterno, OPPORTUNITA)
    return True


def riga(r):
    p = r.proprieta
    if r.tipo == AZIENDE:
        return p.get("Name", ""), f"{p.get('Website') or ''} {p.get('BillingCity') or ''}"
    if r.tipo == OPPORTUNITA:
        return p.get("Name", ""), f"{p.get('Amount') or ''} € · {p.get('StageName') or ''}"
    return f"{p.get('FirstName') or ''} {p.get('LastName') or ''}", f"{p.get('Email') or ''} {p.get('Phone') or ''} {p.get('Title') or ''}"
