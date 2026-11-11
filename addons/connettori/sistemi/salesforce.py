"""Salesforce: persone (Contact), aziende (Account) e opportunità (Opportunity), con il flusso OAuth «client
credentials» di una Connected App (o External Client App) sul My Domain dell'organizzazione.

Documentazione: developer.salesforce.com, REST API e SOQL. Il token si chiede a
https://<dominio>.my.salesforce.com/services/oauth2/token e non ha refresh token: scaduto, se ne chiede un altro. Le
letture usano SystemModstamp (indicizzato, cambia anche con i processi automatici), date senza virgolette in SOQL,
pagine con nextRecordsUrl. La persona sta in un'azienda con AccountId; l'opportunità con AccountId e, per le persone,
con OpportunityContactRole. Le fasi si leggono da OpportunityStage (IsClosed, IsWon, DefaultProbability)."""
import datetime
import json
from urllib.parse import urlsplit

import httpx2 as httpx
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .base import (AZIENDE, OPPORTUNITA, PERSONE, Deposito, ErroreConnettore, ErroreTemporaneo, Sistema, data, dominio,
                   nazione, nome_e_cognome, pieni, pulisci)
from .hubspot import importo

VERSIONE = "v66.0"
OGGETTI = {PERSONE: "Contact", AZIENDE: "Account", OPPORTUNITA: "Opportunity"}
CAMPI = {
    PERSONE: ["Id", "FirstName", "LastName", "Email", "Phone", "MobilePhone", "Title", "MailingStreet", "MailingCity", "MailingPostalCode",
              "AccountId", "SystemModstamp"],
    AZIENDE: ["Id", "Name", "Website", "Phone", "BillingStreet", "BillingCity", "BillingPostalCode", "BillingCountry", "SystemModstamp"],
    OPPORTUNITA: ["Id", "Name", "Amount", "CloseDate", "StageName", "Description", "AccountId", "SystemModstamp"],
}
PER_PAGINA = 200                     # Sforce-Query-Options: batchSize va da 200 a 2000
TEMPO = 20
DURATA_TOKEN = datetime.timedelta(minutes=30)     # la risposta non dice la scadenza: si richiede prima, e comunque al 401
GIORNI_CHIUSURA = 30                 # CloseDate è obbligatoria: se adabox non ce l'ha, a un mese da oggi


def dominio_valido(valore):
    """«acme.my.salesforce.com» (anche con https:// davanti, o una sandbox «acme--dev.sandbox.my.salesforce.com»).
    Solo il My Domain: il segreto della Connected App non va mandato altrove."""
    valore = (valore or "").strip().lower()
    host = urlsplit(valore if "://" in valore else f"https://{valore}").hostname or ""
    if not host.endswith(".my.salesforce.com") or host.count(".") < 3:
        raise ErroreConnettore("Indica il My Domain di Salesforce, per esempio «azienda.my.salesforce.com».")
    return host


def _istanza_valida(url):
    parti = urlsplit(url or "")
    if parti.scheme != "https" or not (parti.hostname or "").endswith(".salesforce.com"):
        raise ErroreConnettore("Salesforce ha risposto con un indirizzo dell'istanza inatteso.")
    return f"https://{parti.hostname}"


def testo(valore):
    """Un valore tra apici in SOQL."""
    return "'" + str(valore).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _quando(istante):
    return istante.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Salesforce(Sistema):
    nome, etichetta = "salesforce", "Salesforce"

    def __init__(self, dominio_sf, client_id, segreto, deposito=None, transport=None):
        self.host = dominio_valido(dominio_sf)
        self.client_id, self.segreto = client_id, segreto
        self.deposito = deposito or Deposito()
        self.http = httpx.Client(timeout=TEMPO, transport=transport, trust_env=False, follow_redirects=False)
        self._accesso = None

    # --- accesso -----------------------------------------------------------------------------------------------------

    def _token(self, nuovo=False):
        if self._accesso is None and not nuovo and (salvato := self.deposito.leggi()):
            try:
                self._accesso = json.loads(salvato)
            except ValueError:
                self._accesso = None
        if self._accesso is None or nuovo:
            try:
                r = self.http.post(f"https://{self.host}/services/oauth2/token",
                                   data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.segreto})
            except httpx.HTTPError as e:
                raise ErroreTemporaneo(f"Salesforce non raggiungibile: {type(e).__name__}") from e
            if r.status_code == 429 or r.status_code >= 500:
                raise ErroreTemporaneo(f"Salesforce risponde {r.status_code}: si riprova più tardi")
            try:
                dati = r.json()
            except ValueError:
                dati = {}
            if r.status_code >= 400 or not dati.get("access_token"):
                raise ErroreConnettore("Salesforce non dà l'accesso: controlla il My Domain, client id e segreto della Connected App e che "
                                       f"il flusso «client credentials» abbia un utente «Run As» ({str(dati.get('error', r.status_code))[:60]}).")
            self._accesso = {"token": dati["access_token"], "istanza": _istanza_valida(dati.get("instance_url"))}
            self.deposito.salva(json.dumps(self._accesso), timezone.now() + DURATA_TOKEN)
        return self._accesso

    def _chiama(self, metodo, percorso, ripeti=True, headers=None, **kwargs):
        accesso = self._token()
        try:
            r = self.http.request(metodo, accesso["istanza"] + percorso, headers={"Authorization": f"Bearer {accesso['token']}", **(headers or {})},
                                  **kwargs)
        except httpx.HTTPError as e:
            raise ErroreTemporaneo(f"Salesforce non raggiungibile: {type(e).__name__}") from e
        if r.status_code == 401 and ripeti:              # INVALID_SESSION_ID: token scaduto, se ne prende un altro
            self._token(nuovo=True)
            return self._chiama(metodo, percorso, ripeti=False, headers=headers, **kwargs)
        errori = _errori(r)
        if r.status_code == 429 or r.status_code >= 500 or "REQUEST_LIMIT_EXCEEDED" in errori:
            raise ErroreTemporaneo(f"Salesforce risponde {r.status_code}: si riprova più tardi")
        if r.status_code in (401, 403):
            raise ErroreConnettore("Salesforce rifiuta l'accesso: controlla i permessi dell'utente «Run As» della Connected App "
                                   f"(Contact, Account, Opportunity in lettura e scrittura). {errori[:150]}".strip())
        if r.status_code >= 400:
            raise ErroreConnettore(f"Salesforce risponde {r.status_code}: {errori[:200]}")
        return r.json() if r.content else {}

    def _query(self, soql):
        return self._chiama("GET", f"/services/data/{VERSIONE}/query", params={"q": soql})

    def verifica(self):
        self._query("SELECT Id FROM Contact LIMIT 1")

    # --- lettura dei record cambiati -------------------------------------------------------------------------------

    def modificati(self, tipo, da, dopo=None):
        opzioni = {"Sforce-Query-Options": f"batchSize={PER_PAGINA}"}
        if dopo:
            if not str(dopo).startswith("/services/data/"):
                raise ErroreConnettore("Pagina successiva di Salesforce non valida.")
            dati = self._chiama("GET", dopo, headers=opzioni)
        else:
            soql = (f"SELECT {', '.join(CAMPI[tipo])} FROM {OGGETTI[tipo]} WHERE SystemModstamp >= {_quando(da)} "
                    "ORDER BY SystemModstamp ASC")
            dati = self._chiama("GET", f"/services/data/{VERSIONE}/query", params={"q": soql}, headers=opzioni)
        record = [{**r, "id": r["Id"]} for r in dati.get("records", [])]
        return record, None if dati.get("done", True) else dati.get("nextRecordsUrl")

    def istante(self, tipo, record):
        return parse_datetime(record.get("SystemModstamp") or "")

    # --- associazioni --------------------------------------------------------------------------------------------------

    def associazioni(self, tipo, verso, record):
        if verso == AZIENDE:
            return {r["id"]: [r["AccountId"]] for r in record if r.get("AccountId")}
        if tipo == OPPORTUNITA and verso == PERSONE and record:
            ids = ", ".join(testo(r["id"]) for r in record)
            ruoli = self._query(f"SELECT OpportunityId, ContactId FROM OpportunityContactRole WHERE OpportunityId IN ({ids}) "
                                "ORDER BY IsPrimary DESC").get("records", [])
            voci = {}
            for ruolo in ruoli:
                voci.setdefault(ruolo["OpportunityId"], []).append(ruolo["ContactId"])
            return voci
        return {}

    def associa(self, tipo, id_esterno, verso, id_verso):
        if verso == AZIENDE:
            self.aggiorna(tipo, id_esterno, {"AccountId": id_verso})
            return
        if tipo == OPPORTUNITA and verso == PERSONE:
            ruoli = self._query(f"SELECT ContactId FROM OpportunityContactRole WHERE OpportunityId = {testo(id_esterno)}").get("records", [])
            if any(r["ContactId"] == id_verso for r in ruoli):
                return
            self._chiama("POST", f"/services/data/{VERSIONE}/sobjects/OpportunityContactRole/",
                         json={"OpportunityId": id_esterno, "ContactId": id_verso, "IsPrimary": not ruoli})

    # --- ricerca, creazione, modifica ------------------------------------------------------------------------------

    def trova(self, tipo, chiave, valore):
        if chiave == "dominio":
            simile = str(valore).replace("\\", "\\\\").replace("'", "\\'").replace("%", "\\%").replace("_", "\\_")
            voci = self._query(f"SELECT Id, Website FROM Account WHERE Website LIKE '%{simile}%' LIMIT 20").get("records", [])
            ids = [r["Id"] for r in voci if dominio(r.get("Website")) == valore]
        else:
            campo = {"email": "Email", "nome": "Name"}[chiave]
            ids = [r["Id"] for r in self._query(f"SELECT Id FROM {OGGETTI[tipo]} WHERE {campo} = {testo(valore)} LIMIT 2").get("records", [])]
        return ids[0] if len(ids) == 1 else (None if not ids else False)

    def crea(self, tipo, dati):
        if tipo == OPPORTUNITA:              # obbligatori in Salesforce: si mettono solo alla creazione
            dati = {"CloseDate": (timezone.localdate() + datetime.timedelta(days=GIORNI_CHIUSURA)).isoformat(), **dati}
            if "StageName" not in dati:
                aperte = [f for f in self.fasi() if not f["chiusa"]]
                if not aperte:
                    raise ErroreConnettore("Salesforce non ha fasi aperte per le opportunità.")
                dati["StageName"] = aperte[0]["id"]
        return self._chiama("POST", f"/services/data/{VERSIONE}/sobjects/{OGGETTI[tipo]}/", json=dati)["id"]

    def aggiorna(self, tipo, id_esterno, dati):
        self._chiama("PATCH", f"/services/data/{VERSIONE}/sobjects/{OGGETTI[tipo]}/{id_esterno}", json=dati)

    # --- fasi ------------------------------------------------------------------------------------------------------------

    def fasi(self):
        """Da OpportunityStage. StageName si scrive con l'ApiName (che di solito coincide con l'etichetta); le
        organizzazioni dove il campo non si legge usano l'etichetta."""
        campi = "MasterLabel, DefaultProbability, IsClosed, IsWon, SortOrder"
        try:
            voci = self._query(f"SELECT ApiName, {campi} FROM OpportunityStage WHERE IsActive = true ORDER BY SortOrder").get("records", [])
        except ErroreTemporaneo:
            raise
        except ErroreConnettore:
            voci = self._query(f"SELECT {campi} FROM OpportunityStage WHERE IsActive = true ORDER BY SortOrder").get("records", [])
        return [{"id": f.get("ApiName") or f["MasterLabel"], "label": f["MasterLabel"], "ordine": f.get("SortOrder") or 0,
                 "probabilita": float(f.get("DefaultProbability") or 0) / 100, "chiusa": bool(f.get("IsClosed")), "vinta": bool(f.get("IsWon"))}
                for f in voci]

    # --- i campi -----------------------------------------------------------------------------------------------------

    def in_adabox(self, tipo, r, fasi=None):
        if tipo == AZIENDE:
            return pulisci({"nome": r.get("Name"), "telefono": r.get("Phone"), "indirizzo": r.get("BillingStreet"), "citta": r.get("BillingCity"),
                            "cap": r.get("BillingPostalCode"), "sito": r.get("Website"), "nazione": nazione(r.get("BillingCountry"))})
        if tipo == OPPORTUNITA:
            dati = {}
            if (r.get("Name") or "").strip():
                dati["titolo"] = r["Name"].strip()[:200]
            if (valore := importo(r.get("Amount"))) is not None:
                dati["valore_atteso"] = valore
            if giorno := data(r.get("CloseDate")):
                dati["chiusura_prevista"] = giorno
            fase = next((f for f in fasi or [] if r.get("StageName") in (f["id"], f["label"])), None)
            if fase is not None:
                dati["fase_esterna"] = fase
            return dati
        nome = " ".join(x for x in [(r.get("FirstName") or "").strip(), (r.get("LastName") or "").strip()] if x)
        return pulisci({"nome": nome or (r.get("Email") or "").strip(), "email": (r.get("Email") or "").strip().lower(), "telefono": r.get("Phone"),
                        "cellulare": r.get("MobilePhone"), "ruolo": r.get("Title"), "indirizzo": r.get("MailingStreet"),
                        "citta": r.get("MailingCity"), "cap": r.get("MailingPostalCode")})

    def fuori(self, tipo, obj, fase=None):
        if tipo == AZIENDE:
            return pieni({"Name": obj.nome, "Website": obj.sito, "Phone": obj.telefono, "BillingStreet": obj.indirizzo, "BillingCity": obj.citta,
                          "BillingPostalCode": obj.cap, "BillingCountry": obj.nazione})
        if tipo == OPPORTUNITA:
            dati = pieni({"Name": obj.titolo, "Amount": float(obj.valore_atteso) if obj.valore_atteso else None,
                          "CloseDate": obj.chiusura_prevista.isoformat() if obj.chiusura_prevista else None,
                          "Description": obj.note[:32000] if obj.note else None})
            if fase is not None:
                dati["StageName"] = fase["id"]
            return dati
        nome, cognome = nome_e_cognome(obj.nome)
        if not cognome:                      # LastName è obbligatorio: un nome solo va lì
            nome, cognome = "", nome
        return pieni({"FirstName": nome, "LastName": cognome, "Email": obj.email, "Phone": obj.telefono, "MobilePhone": obj.cellulare,
                      "Title": obj.ruolo, "MailingStreet": obj.indirizzo, "MailingCity": obj.citta, "MailingPostalCode": obj.cap})


def _errori(r):
    """«REQUIRED_FIELD_MISSING: Required fields are missing: [LastName]» dalla lista di errori di Salesforce."""
    if r.status_code < 400 or not r.content:
        return ""
    try:
        corpo = r.json()
    except ValueError:
        return ""
    voci = corpo if isinstance(corpo, list) else [corpo]
    return "; ".join(f"{v.get('errorCode') or v.get('error', '')}: {v.get('message') or v.get('error_description', '')}".strip(": ")
                     for v in voci if isinstance(v, dict))

