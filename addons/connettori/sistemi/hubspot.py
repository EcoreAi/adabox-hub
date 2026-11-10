"""HubSpot: persone (contacts), aziende (companies) e opportunità (deals), con le associazioni tra loro, con un token
di app privata (Authorization: Bearer). Solo l'indirizzo fisso di HubSpot.

Documentazione: developers.hubspot.com, CRM objects, CRM search, associations v4, pipelines. Ricerca: massimo 200 per
pagina e 10.000 per interrogazione; i record modificati compaiono con qualche istante di ritardo; quelli archiviati
non compaiono. La data di modifica è `lastmodifieddate` per le persone e `hs_lastmodifieddate` per gli altri."""
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx2 as httpx
from django.utils.dateparse import parse_datetime

from .base import (AZIENDE, OPPORTUNITA, PERSONE, ErroreConnettore, ErroreTemporaneo, Sistema, data, dominio, nazione,
                   nome_e_cognome, pieni, pulisci)

BASE = "https://api.hubapi.com"
CONTATTI = PERSONE
OGGETTI = {
    CONTATTI: {"modificato": "lastmodifieddate",
               "proprieta": ["email", "firstname", "lastname", "phone", "mobilephone", "jobtitle", "address", "city", "zip", "website"]},
    AZIENDE: {"modificato": "hs_lastmodifieddate",
              "proprieta": ["name", "domain", "website", "phone", "address", "city", "zip", "country", "state"]},
    OPPORTUNITA: {"modificato": "hs_lastmodifieddate",
                  "proprieta": ["dealname", "amount", "closedate", "dealstage", "pipeline", "description"]},
}
CHIAVI = {"email": "email", "dominio": "domain", "nome": "name"}
PER_PAGINA = 100
TEMPO = 20
AMBITI = "crm.objects.contacts, crm.objects.companies e crm.objects.deals (lettura e scrittura)"


def _id(valore):
    return quote(str(valore), safe="")


class HubSpot(Sistema):
    nome, etichetta = "hubspot", "HubSpot"

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

    def modificati(self, tipo, da, dopo=None):
        campo = OGGETTI[tipo]["modificato"]
        corpo = {"filterGroups": [{"filters": [{"propertyName": campo, "operator": "GTE", "value": str(int(da.timestamp() * 1000))}]}],
                 "sorts": [{"propertyName": campo, "direction": "ASCENDING"}],
                 "properties": OGGETTI[tipo]["proprieta"] + [campo], "limit": PER_PAGINA}
        if dopo:
            corpo["after"] = dopo
        dati = self._chiama("POST", f"/crm/v3/objects/{tipo}/search", json=corpo)
        return dati.get("results", []), (dati.get("paging") or {}).get("next", {}).get("after")

    def istante(self, tipo, record):
        return parse_datetime((record.get("properties") or {}).get(OGGETTI[tipo]["modificato"]) or "")

    # --- ricerca, creazione, modifica ------------------------------------------------------------------------------

    def trova(self, tipo, chiave, valore):
        proprieta = CHIAVI[chiave]
        corpo = {"filterGroups": [{"filters": [{"propertyName": proprieta, "operator": "EQ", "value": valore}]}],
                 "properties": [proprieta], "limit": 2}
        risultati = self._chiama("POST", f"/crm/v3/objects/{tipo}/search", json=corpo).get("results", [])
        return risultati[0]["id"] if len(risultati) == 1 else (None if not risultati else False)

    def crea(self, tipo, dati):
        return self._chiama("POST", f"/crm/v3/objects/{tipo}", json={"properties": dati})["id"]

    def aggiorna(self, tipo, id_esterno, dati):
        self._chiama("PATCH", f"/crm/v3/objects/{tipo}/{_id(id_esterno)}", json={"properties": dati})

    # --- associazioni (v4) -----------------------------------------------------------------------------------------

    def associazioni(self, tipo, verso, record):
        """Al massimo 100 record per chiamata, come le pagine."""
        if not record:
            return {}
        dati = self._chiama("POST", f"/crm/v4/associations/{tipo}/{verso}/batch/read", json={"inputs": [{"id": str(r["id"])} for r in record]})
        return {str(r["from"]["id"]): [str(t["toObjectId"]) for t in r.get("to", [])] for r in dati.get("results", [])}

    def associa(self, tipo, id_esterno, verso, id_verso):
        """L'associazione predefinita tra due record (se c'è già, HubSpot non la duplica)."""
        self._chiama("PUT", f"/crm/v4/objects/{tipo}/{_id(id_esterno)}/associations/default/{verso}/{_id(id_verso)}")

    # --- fasi delle opportunità ------------------------------------------------------------------------------------

    def fasi(self):
        """Le fasi della pipeline predefinita: chiusa al 100% è la vittoria, chiusa sotto è persa."""
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
            chiusa = str(meta.get("isClosed", "false")).lower() == "true"
            voci.append({"id": f["id"], "label": f.get("label", f["id"]), "ordine": f.get("displayOrder", 0),
                         "probabilita": probabilita, "chiusa": chiusa, "vinta": chiusa and probabilita >= 1, "pipeline": scelta["id"]})
        return sorted(voci, key=lambda f: f["ordine"])

    # --- i campi -----------------------------------------------------------------------------------------------------

    def in_adabox(self, tipo, record, fasi=None):
        if tipo == AZIENDE:
            return azienda_in_adabox(record)
        if tipo == OPPORTUNITA:
            return opportunita_in_adabox(record, fasi or [])
        return in_adabox(record)

    def fuori(self, tipo, obj, fase=None):
        if tipo == AZIENDE:
            return azienda_in_hubspot(obj)
        if tipo == OPPORTUNITA:
            return opportunita_in_hubspot(obj, fase)
        return in_hubspot(obj)


# --- dai dati di HubSpot a quelli di adabox, e ritorno -------------------------------------------------------------

def in_adabox(record):
    p = record.get("properties") or {}
    nome = " ".join(x for x in [(p.get("firstname") or "").strip(), (p.get("lastname") or "").strip()] if x)
    dati = {"nome": nome or (p.get("email") or "").strip(), "email": (p.get("email") or "").strip().lower(), "telefono": p.get("phone"),
            "cellulare": p.get("mobilephone"), "ruolo": p.get("jobtitle"), "indirizzo": p.get("address"), "citta": p.get("city"),
            "cap": p.get("zip"), "sito": p.get("website")}
    return pulisci(dati)


def in_hubspot(contatto):
    nome, cognome = nome_e_cognome(contatto.nome)
    return pieni({"email": contatto.email, "firstname": nome, "lastname": cognome, "phone": contatto.telefono, "mobilephone": contatto.cellulare,
                  "jobtitle": contatto.ruolo, "address": contatto.indirizzo, "city": contatto.citta, "zip": contatto.cap, "website": contatto.sito})


def azienda_in_adabox(record):
    p = record.get("properties") or {}
    sito = p.get("website") or (f"https://{p['domain']}" if p.get("domain") else "")
    return pulisci({"nome": p.get("name"), "telefono": p.get("phone"), "indirizzo": p.get("address"), "citta": p.get("city"),
                    "cap": p.get("zip"), "sito": sito, "nazione": nazione(p.get("country"))})


def azienda_in_hubspot(contatto):
    return pieni({"name": contatto.nome, "domain": dominio(contatto.sito), "website": contatto.sito, "phone": contatto.telefono,
                  "address": contatto.indirizzo, "city": contatto.citta, "zip": contatto.cap, "country": contatto.nazione})


def importo(testo):
    try:
        return Decimal(str(testo).strip()).quantize(Decimal("0.01")) if str(testo or "").strip() else None
    except InvalidOperation:
        return None


def opportunita_in_adabox(record, fasi):
    p = record.get("properties") or {}
    dati = {}
    if (p.get("dealname") or "").strip():
        dati["titolo"] = p["dealname"].strip()[:200]
    if (valore := importo(p.get("amount"))) is not None:
        dati["valore_atteso"] = valore
    if giorno := data(p.get("closedate")):
        dati["chiusura_prevista"] = giorno
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
    return pieni(dati)
