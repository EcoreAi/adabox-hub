"""HubSpot: i contatti, con un token di app privata (Authorization: Bearer). Solo l'indirizzo fisso di HubSpot.

Documentazione: developers.hubspot.com, CRM contacts e CRM search. Ricerca: massimo 200 per pagina e 10.000 per
interrogazione; i record modificati compaiono con qualche istante di ritardo; quelli archiviati non compaiono."""
from urllib.parse import quote

import httpx2 as httpx

from .base import ErroreConnettore, ErroreTemporaneo

BASE = "https://api.hubapi.com"
PROPRIETA = ["email", "firstname", "lastname", "phone", "mobilephone", "jobtitle", "address", "city", "zip", "website", "lastmodifieddate"]
PER_PAGINA = 100
TEMPO = 20


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
            raise ErroreConnettore("HubSpot rifiuta il token: controlla il token e gli ambiti crm.objects.contacts dell'app privata")
        if r.status_code >= 400:
            try:
                messaggio = r.json().get("message", "")
            except ValueError:
                messaggio = ""
            raise ErroreConnettore(f"HubSpot risponde {r.status_code}: {messaggio[:200]}")
        return r.json() if r.content else {}

    def verifica(self):
        self._chiama("GET", "/crm/v3/objects/contacts", params={"limit": 1})

    def modificati_da(self, millisecondi, dopo=None):
        """(record, prossima pagina). Dal meno recente: così il cursore avanza anche se ci si ferma a metà."""
        corpo = {"filterGroups": [{"filters": [{"propertyName": "lastmodifieddate", "operator": "GTE", "value": str(millisecondi)}]}],
                 "sorts": [{"propertyName": "lastmodifieddate", "direction": "ASCENDING"}], "properties": PROPRIETA, "limit": PER_PAGINA}
        if dopo:
            corpo["after"] = dopo
        dati = self._chiama("POST", "/crm/v3/objects/contacts/search", json=corpo)
        return dati.get("results", []), (dati.get("paging") or {}).get("next", {}).get("after")

    def trova_per_email(self, email):
        corpo = {"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}], "properties": ["email"], "limit": 1}
        risultati = self._chiama("POST", "/crm/v3/objects/contacts/search", json=corpo).get("results", [])
        return risultati[0]["id"] if risultati else None

    def crea(self, proprieta):
        return self._chiama("POST", "/crm/v3/objects/contacts", json={"properties": proprieta})["id"]

    def aggiorna(self, id_esterno, proprieta):
        self._chiama("PATCH", f"/crm/v3/objects/contacts/{quote(str(id_esterno), safe='')}", json={"properties": proprieta})


def in_adabox(record):
    """Dai campi di HubSpot a quelli del contatto; i campi vuoti restano fuori: non cancellano ciò che c'è da noi."""
    p = record.get("properties") or {}
    nome = " ".join(x for x in [(p.get("firstname") or "").strip(), (p.get("lastname") or "").strip()] if x)
    dati = {"nome": nome or (p.get("email") or "").strip(), "email": (p.get("email") or "").strip().lower(), "telefono": p.get("phone"),
            "cellulare": p.get("mobilephone"), "ruolo": p.get("jobtitle"), "indirizzo": p.get("address"), "citta": p.get("city"),
            "cap": p.get("zip"), "sito": p.get("website")}
    return {k: str(v).strip() for k, v in dati.items() if v and str(v).strip()}


def in_hubspot(contatto):
    """Dal contatto a HubSpot: nome e cognome si separano sul primo spazio, l'unica divisione che non inventa nulla."""
    nome, _, cognome = contatto.nome.strip().partition(" ")
    dati = {"email": contatto.email, "firstname": nome, "lastname": cognome, "phone": contatto.telefono, "mobilephone": contatto.cellulare,
            "jobtitle": contatto.ruolo, "address": contatto.indirizzo, "city": contatto.citta, "zip": contatto.cap, "website": contatto.sito}
    return {k: v for k, v in dati.items() if v}
