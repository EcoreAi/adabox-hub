"""HubSpot: persone (contacts), aziende (companies) e opportunità (deals), con le associazioni tra loro, con un token
di app privata (Authorization: Bearer). Solo l'indirizzo fisso di HubSpot.

Documentazione: developers.hubspot.com, CRM objects, CRM search, associations v4, pipelines. Ricerca: massimo 200 per
pagina e 10.000 per interrogazione; i record modificati compaiono con qualche istante di ritardo; quelli archiviati
non compaiono. La data di modifica è `lastmodifieddate` per le persone e `hs_lastmodifieddate` per gli altri."""
import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlsplit

import httpx2 as httpx

from .base import ErroreConnettore, ErroreTemporaneo

BASE = "https://api.hubapi.com"
CONTATTI, AZIENDE, OPPORTUNITA = "contacts", "companies", "deals"
OGGETTI = {
    CONTATTI: {"modificato": "lastmodifieddate",
               "proprieta": ["email", "firstname", "lastname", "phone", "mobilephone", "jobtitle", "address", "city", "zip", "website"]},
    AZIENDE: {"modificato": "hs_lastmodifieddate",
              "proprieta": ["name", "domain", "website", "phone", "address", "city", "zip", "country", "state"]},
    OPPORTUNITA: {"modificato": "hs_lastmodifieddate",
                  "proprieta": ["dealname", "amount", "closedate", "dealstage", "pipeline", "description"]},
}
PROPRIETA = OGGETTI[CONTATTI]["proprieta"] + ["lastmodifieddate"]       # compatibilità: le persone
PER_PAGINA = 100
TEMPO = 20
AMBITI = "crm.objects.contacts, crm.objects.companies e crm.objects.deals (lettura e scrittura)"


def _id(valore):
    return quote(str(valore), safe="")


class HubSpot:
    nome = "hubspot"

    def __init__(self, token, transport=None):
        self.client = httpx.Client(base_url=BASE, timeout=TEMPO, transport=transport, trust_env=False, follow_redirects=False,
                                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    def _chiama(self, metodo, percorso, **kwargs):
        try:
            r = self.client.request(metodo, percorso, **kwargs)
        except httpx.HTTPError as e:
            raise ErroreTemporaneo(f"HubSpot non raggiungibile: {type(e).__name__}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise ErroreTemporaneo(f"HubSpot risponde {r.status_code}: si riprova più tardi")
        if r.status_code in (401, 403):
            raise ErroreConnettore(f"HubSpot rifiuta il token: controlla il token e gli ambiti {AMBITI} dell'app privata")
        if r.status_code >= 400:
            try:
                messaggio = r.json().get("message", "")
            except ValueError:
                messaggio = ""
            raise ErroreConnettore(f"HubSpot risponde {r.status_code}: {messaggio[:200]}")
        return r.json() if r.content else {}

    def verifica(self):
        self._chiama("GET", "/crm/v3/objects/contacts", params={"limit": 1})

    # --- lettura dei record cambiati -------------------------------------------------------------------------------

    def modificati(self, oggetto, millisecondi, dopo=None):
        """(record, prossima pagina) di un tipo di oggetto. Dal meno recente: così il cursore avanza anche se ci si
        ferma a metà."""
        campo = OGGETTI[oggetto]["modificato"]
        corpo = {"filterGroups": [{"filters": [{"propertyName": campo, "operator": "GTE", "value": str(millisecondi)}]}],
                 "sorts": [{"propertyName": campo, "direction": "ASCENDING"}],
                 "properties": OGGETTI[oggetto]["proprieta"] + [campo], "limit": PER_PAGINA}
        if dopo:
            corpo["after"] = dopo
        dati = self._chiama("POST", f"/crm/v3/objects/{oggetto}/search", json=corpo)
        return dati.get("results", []), (dati.get("paging") or {}).get("next", {}).get("after")

    def modificati_da(self, millisecondi, dopo=None):
        """Le persone cambiate (il primo oggetto gestito, resta per compatibilità)."""
        return self.modificati(CONTATTI, millisecondi, dopo)

    # --- ricerca, creazione, modifica ------------------------------------------------------------------------------

    def trova(self, oggetto, proprieta, valore):
        """L'id del primo record con quel valore, o None. Per le chiavi naturali: email delle persone, dominio o nome
        delle aziende."""
        corpo = {"filterGroups": [{"filters": [{"propertyName": proprieta, "operator": "EQ", "value": valore}]}],
                 "properties": [proprieta], "limit": 2}
        risultati = self._chiama("POST", f"/crm/v3/objects/{oggetto}/search", json=corpo).get("results", [])
        return risultati[0]["id"] if len(risultati) == 1 else (None if not risultati else False)

    def trova_per_email(self, email):
        trovato = self.trova(CONTATTI, "email", email)
        return trovato or None

    def crea(self, proprieta, oggetto=CONTATTI):
        return self._chiama("POST", f"/crm/v3/objects/{oggetto}", json={"properties": proprieta})["id"]

    def aggiorna(self, id_esterno, proprieta, oggetto=CONTATTI):
        self._chiama("PATCH", f"/crm/v3/objects/{oggetto}/{_id(id_esterno)}", json={"properties": proprieta})

    # --- associazioni (v4) -----------------------------------------------------------------------------------------

    def associazioni(self, da, a, ids):
        """{id di partenza: [id associati]} per un gruppo di record (al massimo 100 per chiamata, come le pagine)."""
        if not ids:
            return {}
        dati = self._chiama("POST", f"/crm/v4/associations/{da}/{a}/batch/read", json={"inputs": [{"id": str(i)} for i in ids]})
        return {str(r["from"]["id"]): [str(t["toObjectId"]) for t in r.get("to", [])] for r in dati.get("results", [])}

    def associa(self, da, id_da, a, id_a):
        """L'associazione predefinita tra due record (se c'è già, HubSpot non la duplica)."""
        self._chiama("PUT", f"/crm/v4/objects/{da}/{_id(id_da)}/associations/default/{a}/{_id(id_a)}")

    # --- fasi delle opportunità ------------------------------------------------------------------------------------

    def fasi(self):
        """Le fasi della pipeline predefinita delle opportunità: [{id, label, ordine, probabilita, chiusa}]."""
        pipeline = self._chiama("GET", "/crm/v3/pipelines/deals").get("results", [])
        scelta = next((p for p in pipeline if p.get("id") == "default"), pipeline[0] if pipeline else None)
        if scelta is None:
            return []
        voci = []
        for f in scelta.get("stages", []):
            meta = f.get("metadata") or {}
            try:
                probabilita = float(meta.get("probability", 0))
            except (TypeError, ValueError):
                probabilita = 0.0
            voci.append({"id": f["id"], "label": f.get("label", f["id"]), "ordine": f.get("displayOrder", 0),
                         "probabilita": probabilita, "chiusa": str(meta.get("isClosed", "false")).lower() == "true",
                         "pipeline": scelta["id"]})
        return sorted(voci, key=lambda f: f["ordine"])


# --- dai dati di HubSpot a quelli di adabox, e ritorno -------------------------------------------------------------

def _pulisci(dati):
    return {k: str(v).strip() for k, v in dati.items() if v is not None and str(v).strip()}


def in_adabox(record):
    """Dai campi di HubSpot a quelli del contatto; i campi vuoti restano fuori: non cancellano ciò che c'è da noi."""
    p = record.get("properties") or {}
    nome = " ".join(x for x in [(p.get("firstname") or "").strip(), (p.get("lastname") or "").strip()] if x)
    dati = {"nome": nome or (p.get("email") or "").strip(), "email": (p.get("email") or "").strip().lower(), "telefono": p.get("phone"),
            "cellulare": p.get("mobilephone"), "ruolo": p.get("jobtitle"), "indirizzo": p.get("address"), "citta": p.get("city"),
            "cap": p.get("zip"), "sito": p.get("website")}
    return _pulisci(dati)


def in_hubspot(contatto):
    """Dal contatto a HubSpot: nome e cognome si separano sul primo spazio, l'unica divisione che non inventa nulla."""
    nome, _, cognome = contatto.nome.strip().partition(" ")
    dati = {"email": contatto.email, "firstname": nome, "lastname": cognome, "phone": contatto.telefono, "mobilephone": contatto.cellulare,
            "jobtitle": contatto.ruolo, "address": contatto.indirizzo, "city": contatto.citta, "zip": contatto.cap, "website": contatto.sito}
    return {k: v for k, v in dati.items() if v}


def dominio(sito):
    """«https://www.rossi.it/chi-siamo» → «rossi.it»: la chiave con cui HubSpot riconosce le aziende."""
    sito = (sito or "").strip().lower()
    if not sito:
        return ""
    host = urlsplit(sito if "://" in sito else f"https://{sito}").hostname or ""
    return host[4:] if host.startswith("www.") else host


def azienda_in_adabox(record):
    p = record.get("properties") or {}
    sito = p.get("website") or (f"https://{p['domain']}" if p.get("domain") else "")
    nazione = (p.get("country") or "").strip()
    dati = {"nome": p.get("name"), "telefono": p.get("phone"), "indirizzo": p.get("address"), "citta": p.get("city"),
            "cap": p.get("zip"), "sito": sito, "nazione": nazione.upper() if len(nazione) == 2 else None}
    return _pulisci(dati)


def azienda_in_hubspot(contatto):
    dati = {"name": contatto.nome, "domain": dominio(contatto.sito), "website": contatto.sito, "phone": contatto.telefono,
            "address": contatto.indirizzo, "city": contatto.citta, "zip": contatto.cap, "country": contatto.nazione}
    return {k: v for k, v in dati.items() if v}


def _data(testo):
    """La data di un valore di HubSpot: ISO («2026-11-30T00:00:00Z» o «2026-11-30») oppure millisecondi."""
    testo = (testo or "").strip()
    if not testo:
        return None
    if testo.isdigit():
        return datetime.datetime.fromtimestamp(int(testo) / 1000, tz=datetime.timezone.utc).date()
    try:
        return datetime.date.fromisoformat(testo[:10])
    except ValueError:
        return None


def opportunita_in_adabox(record, fasi):
    """I campi dell'opportunità e lo stato dalla fase: chiusa al 100% è vinta, chiusa allo 0% è persa."""
    p = record.get("properties") or {}
    dati = {}
    if (p.get("dealname") or "").strip():
        dati["titolo"] = p["dealname"].strip()[:200]
    if (p.get("amount") or "").strip():
        try:
            dati["valore_atteso"] = Decimal(p["amount"]).quantize(Decimal("0.01"))
        except InvalidOperation:
            pass
    if data := _data(p.get("closedate")):
        dati["chiusura_prevista"] = data
    fase = next((f for f in fasi if f["id"] == p.get("dealstage")), None)
    if fase is not None:
        dati["fase_esterna"] = fase
    return dati


def opportunita_in_hubspot(opportunita, fase_esterna):
    dati = {"dealname": opportunita.titolo, "amount": f"{opportunita.valore_atteso:f}" if opportunita.valore_atteso else None,
            "closedate": f"{opportunita.chiusura_prevista.isoformat()}T00:00:00Z" if opportunita.chiusura_prevista else None,
            "description": opportunita.note[:65000] if opportunita.note else None}
    if fase_esterna is not None:
        dati["pipeline"], dati["dealstage"] = fase_esterna["pipeline"], fase_esterna["id"]
    return {k: v for k, v in dati.items() if v}
