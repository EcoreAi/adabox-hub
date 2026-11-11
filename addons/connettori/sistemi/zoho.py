"""Zoho CRM: persone (Contacts), aziende (Accounts) e opportunità (Deals), con un refresh token di un «Self Client»
nel data center dell'account (com, eu, in, com.au, jp, ca, sa, com.cn).

Documentazione: zoho.com/crm/developer/docs/api/v8. Il token di accesso dura un'ora e se ne possono chiedere al
massimo 10 ogni 10 minuti per refresh token: per questo si tiene nel deposito e si riusa tra i lavori. Le chiamate
vanno all'api_domain restituito con il token. Le letture usano If-Modified-Since con l'ordine per Modified_Time;
`fields` è obbligatorio. La ricerca con «equals» si comporta come «contiene»: il risultato si filtra qui. Persona e
opportunità si legano all'azienda con il campo Account_Name ({"id": ...}), l'opportunità alla persona con
Contact_Name. Le fasi sono il picklist Stage dei Deals."""
import datetime
import json
from urllib.parse import urlsplit

import httpx2 as httpx
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .base import (AZIENDE, OPPORTUNITA, PERSONE, Deposito, ErroreConnettore, ErroreTemporaneo, Sistema, data, dominio,
                   nazione, nome_e_cognome, pieni, pulisci)
from .hubspot import importo

CENTRI = {  # data center: (server degli account, dominio delle API)
    "com": ("accounts.zoho.com", "www.zohoapis.com"),
    "eu": ("accounts.zoho.eu", "www.zohoapis.eu"),
    "in": ("accounts.zoho.in", "www.zohoapis.in"),
    "com.au": ("accounts.zoho.com.au", "www.zohoapis.com.au"),
    "jp": ("accounts.zoho.jp", "www.zohoapis.jp"),
    "ca": ("accounts.zohocloud.ca", "www.zohoapis.ca"),
    "sa": ("accounts.zoho.sa", "www.zohoapis.sa"),
    "com.cn": ("accounts.zoho.com.cn", "www.zohoapis.com.cn"),
}
MODULI = {PERSONE: "Contacts", AZIENDE: "Accounts", OPPORTUNITA: "Deals"}
CAMPI = {
    PERSONE: ["First_Name", "Last_Name", "Email", "Phone", "Mobile", "Title", "Mailing_Street", "Mailing_City", "Mailing_Zip", "Account_Name",
              "Modified_Time"],
    AZIENDE: ["Account_Name", "Website", "Phone", "Billing_Street", "Billing_City", "Billing_Code", "Billing_Country", "Modified_Time"],
    OPPORTUNITA: ["Deal_Name", "Amount", "Closing_Date", "Stage", "Description", "Account_Name", "Contact_Name", "Modified_Time"],
}
RICERCA = {"email": "Email", "nome": "Account_Name", "dominio": "Website"}
PER_PAGINA = 200
TEMPO = 20
AMBITI = ("ZohoCRM.modules.contacts.ALL, ZohoCRM.modules.accounts.ALL, ZohoCRM.modules.deals.ALL, ZohoCRM.settings.fields.READ, "
          "ZohoSearch.securesearch.READ")


def centro_valido(valore):
    valore = (valore or "").strip().lower().lstrip(".")
    if valore not in CENTRI:
        raise ErroreConnettore(f"Indica il data center di Zoho: uno tra {', '.join(CENTRI)}.")
    return valore


def _api_valida(url, centro):
    host = urlsplit(url or "").hostname or ""
    if not url.startswith("https://") or host not in {api for _, api in CENTRI.values()}:
        raise ErroreConnettore("Zoho ha risposto con un dominio delle API inatteso.")
    return f"https://{host}" if host else f"https://{CENTRI[centro][1]}"


def criterio(valore):
    """Un valore nei criteri di ricerca: parentesi, virgole e barre si precedono con la barra."""
    testo = str(valore)
    for c in ("\\", "(", ")", ","):
        testo = testo.replace(c, "\\" + c)
    return testo


class Zoho(Sistema):
    nome, etichetta = "zoho", "Zoho CRM"

    def __init__(self, centro, client_id, segreto, refresh_token, deposito=None, transport=None):
        self.centro = centro_valido(centro)
        self.client_id, self.segreto, self.refresh_token = client_id, segreto, refresh_token
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
                r = self.http.post(f"https://{CENTRI[self.centro][0]}/oauth/v2/token",
                                   params={"refresh_token": self.refresh_token, "client_id": self.client_id, "client_secret": self.segreto,
                                           "grant_type": "refresh_token"})
            except httpx.HTTPError as e:
                raise ErroreTemporaneo(f"Zoho non raggiungibile: {type(e).__name__}") from e
            if r.status_code == 429 or r.status_code >= 500:
                raise ErroreTemporaneo(f"Zoho risponde {r.status_code}: si riprova più tardi")
            try:
                dati = r.json()
            except ValueError:
                dati = {}
            if dati.get("error") == "Access Denied" or "too many requests" in str(dati.get("error_description", "")).lower():
                raise ErroreTemporaneo("Zoho: troppe richieste di token, si riprova più tardi")
            if r.status_code >= 400 or not dati.get("access_token"):
                raise ErroreConnettore("Zoho non dà l'accesso: controlla data center, client id, segreto e refresh token del Self Client "
                                       f"({str(dati.get('error', r.status_code))[:60]}).")
            self._accesso = {"token": dati["access_token"], "api": _api_valida(dati.get("api_domain") or f"https://{CENTRI[self.centro][1]}", self.centro)}
            durata = int(dati.get("expires_in") or 3600)
            self.deposito.salva(json.dumps(self._accesso), timezone.now() + datetime.timedelta(seconds=max(durata - 120, 60)))
        return self._accesso

    def _chiama(self, metodo, percorso, ripeti=True, headers=None, **kwargs):
        accesso = self._token()
        try:
            r = self.http.request(metodo, accesso["api"] + percorso, headers={"Authorization": f"Zoho-oauthtoken {accesso['token']}", **(headers or {})},
                                  **kwargs)
        except httpx.HTTPError as e:
            raise ErroreTemporaneo(f"Zoho non raggiungibile: {type(e).__name__}") from e
        if r.status_code in (204, 304):
            return {}
        corpo = _corpo(r)
        codice = str(corpo.get("code") or "")
        if r.status_code == 401 and codice in ("INVALID_TOKEN", "INVALID_OAUTHTOKEN", "AUTHENTICATION_FAILURE") and ripeti:
            self._token(nuovo=True)
            return self._chiama(metodo, percorso, ripeti=False, headers=headers, **kwargs)
        if r.status_code == 429 or r.status_code >= 500:
            raise ErroreTemporaneo(f"Zoho risponde {r.status_code}: si riprova più tardi")
        if r.status_code in (401, 403):
            raise ErroreConnettore(f"Zoho rifiuta l'accesso ({codice or r.status_code}): servono gli ambiti {AMBITI}")
        if r.status_code >= 400 and not corpo.get("data"):
            raise ErroreConnettore(f"Zoho risponde {r.status_code}: {codice} {str(corpo.get('message', ''))[:200]}".strip())
        return corpo

    def verifica(self):
        self._chiama("GET", "/crm/v8/Contacts", params={"fields": "Last_Name", "per_page": 1})

    # --- lettura dei record cambiati -------------------------------------------------------------------------------

    def modificati(self, tipo, da, dopo=None):
        parametri = {"fields": ",".join(CAMPI[tipo]), "sort_by": "Modified_Time", "sort_order": "asc", "per_page": PER_PAGINA}
        if dopo and str(dopo).startswith("t:"):
            parametri["page_token"] = dopo[2:]
        else:
            parametri["page"] = int(str(dopo or "p:1")[2:])
        istante = da.astimezone(datetime.timezone.utc).replace(microsecond=0).isoformat()
        dati = self._chiama("GET", f"/crm/v8/{MODULI[tipo]}", params=parametri, headers={"If-Modified-Since": istante})
        info = dati.get("info") or {}
        prossima = None
        if info.get("more_records"):
            prossima = f"t:{info['next_page_token']}" if info.get("next_page_token") else f"p:{int(info.get('page') or parametri.get('page') or 1) + 1}"
        return [{**r, "id": str(r["id"])} for r in dati.get("data", [])], prossima

    def istante(self, tipo, record):
        return parse_datetime(record.get("Modified_Time") or "")

    # --- associazioni --------------------------------------------------------------------------------------------------

    def associazioni(self, tipo, verso, record):
        campo = "Account_Name" if verso == AZIENDE else ("Contact_Name" if tipo == OPPORTUNITA else None)
        if campo is None:
            return {}
        return {r["id"]: [str(r[campo]["id"])] for r in record if isinstance(r.get(campo), dict) and r[campo].get("id")}

    def associa(self, tipo, id_esterno, verso, id_verso):
        campo = "Account_Name" if verso == AZIENDE else "Contact_Name"
        self.aggiorna(tipo, id_esterno, {campo: {"id": str(id_verso)}})

    # --- ricerca, creazione, modifica ------------------------------------------------------------------------------

    def trova(self, tipo, chiave, valore):
        campo = RICERCA[chiave]
        dati = self._chiama("GET", f"/crm/v8/{MODULI[tipo]}/search", params={"criteria": f"({campo}:equals:{criterio(valore)})", "fields": campo,
                                                                         "per_page": 50})
        cercato = str(valore).strip().lower()
        if chiave == "dominio":
            ids = [r["id"] for r in dati.get("data", []) if dominio(r.get(campo)) == cercato]
        else:
            ids = [r["id"] for r in dati.get("data", []) if str(r.get(campo) or "").strip().lower() == cercato]
        return str(ids[0]) if len(ids) == 1 else (None if not ids else False)

    def _esito(self, dati, cosa):
        voce = (dati.get("data") or [{}])[0]
        if str(voce.get("status", "")).lower() == "success":
            return str((voce.get("details") or {}).get("id") or "")
        dettagli = voce.get("details") or {}
        if voce.get("code") == "DUPLICATE_DATA" and dettagli.get("id"):
            return str(dettagli["id"])               # c'è già di là: si collega quello
        campo = dettagli.get("api_name")
        raise ErroreConnettore(f"Zoho rifiuta {cosa}: {voce.get('code', '')} {voce.get('message', '')}{f' ({campo})' if campo else ''}".strip())

    def crea(self, tipo, dati):
        return self._esito(self._chiama("POST", f"/crm/v8/{MODULI[tipo]}", json={"data": [dati]}), "il record")

    def aggiorna(self, tipo, id_esterno, dati):
        self._esito(self._chiama("PUT", f"/crm/v8/{MODULI[tipo]}/{id_esterno}", json={"data": [dati]}), "la modifica")

    # --- fasi ------------------------------------------------------------------------------------------------------------

    def fasi(self):
        """Il picklist Stage dei Deals. Probabilità e tipo (aperta, vinta, persa) si usano se Zoho li manda; se no
        «Closed Won» è vinta, gli altri «Closed …» sono perse e le aperte salgono in ordine."""
        campi = self._chiama("GET", "/crm/v8/settings/fields", params={"module": "Deals"}).get("fields", [])
        stage = next((c for c in campi if c.get("api_name") == "Stage"), None)
        voci = [v for v in (stage or {}).get("pick_list_values", []) if v.get("actual_value") and v.get("actual_value") != "-None-"]
        voci.sort(key=lambda v: v.get("sequence_number") or 0)
        fasi = []
        for i, v in enumerate(voci):
            chiusa, vinta = _esito_fase(v)
            probabilita = v.get("probability")
            fasi.append({"id": v["actual_value"], "label": v.get("display_value") or v["actual_value"], "ordine": v.get("sequence_number") or i,
                         "chiusa": chiusa, "vinta": vinta,
                         "probabilita": float(probabilita) / 100 if isinstance(probabilita, (int, float)) else None})
        aperte = [f for f in fasi if not f["chiusa"]]
        for i, f in enumerate(aperte):
            if f["probabilita"] is None:
                f["probabilita"] = round((i + 1) / (len(aperte) + 1), 2)
        for f in fasi:
            if f["probabilita"] is None:
                f["probabilita"] = 1.0 if f["vinta"] else 0.0
        return fasi

    # --- i campi -----------------------------------------------------------------------------------------------------

    def in_adabox(self, tipo, r, fasi=None):
        if tipo == AZIENDE:
            return pulisci({"nome": r.get("Account_Name"), "telefono": r.get("Phone"), "indirizzo": r.get("Billing_Street"), "citta": r.get("Billing_City"),
                            "cap": r.get("Billing_Code"), "sito": r.get("Website"), "nazione": nazione(r.get("Billing_Country"))})
        if tipo == OPPORTUNITA:
            dati = {}
            if str(r.get("Deal_Name") or "").strip():
                dati["titolo"] = str(r["Deal_Name"]).strip()[:200]
            if (valore := importo(r.get("Amount"))) is not None:
                dati["valore_atteso"] = valore
            if giorno := data(r.get("Closing_Date")):
                dati["chiusura_prevista"] = giorno
            fase = next((f for f in fasi or [] if r.get("Stage") in (f["id"], f["label"])), None)
            if fase is not None:
                dati["fase_esterna"] = fase
            return dati
        nome = " ".join(x for x in [str(r.get("First_Name") or "").strip(), str(r.get("Last_Name") or "").strip()] if x)
        return pulisci({"nome": nome or str(r.get("Email") or "").strip(), "email": str(r.get("Email") or "").strip().lower(), "telefono": r.get("Phone"),
                        "cellulare": r.get("Mobile"), "ruolo": r.get("Title"), "indirizzo": r.get("Mailing_Street"), "citta": r.get("Mailing_City"),
                        "cap": r.get("Mailing_Zip")})

    def fuori(self, tipo, obj, fase=None):
        if tipo == AZIENDE:
            return pieni({"Account_Name": obj.nome, "Website": obj.sito, "Phone": obj.telefono, "Billing_Street": obj.indirizzo,
                          "Billing_City": obj.citta, "Billing_Code": obj.cap, "Billing_Country": obj.nazione})
        if tipo == OPPORTUNITA:
            dati = pieni({"Deal_Name": obj.titolo, "Amount": float(obj.valore_atteso) if obj.valore_atteso else None,
                          "Closing_Date": obj.chiusura_prevista.isoformat() if obj.chiusura_prevista else None,
                          "Description": obj.note[:32000] if obj.note else None})
            if fase is not None:
                dati["Stage"] = fase["id"]
            return dati
        nome, cognome = nome_e_cognome(obj.nome)
        if not cognome:                      # Last_Name è obbligatorio: un nome solo va lì
            nome, cognome = "", nome
        return pieni({"First_Name": nome, "Last_Name": cognome, "Email": obj.email, "Phone": obj.telefono, "Mobile": obj.cellulare, "Title": obj.ruolo,
                      "Mailing_Street": obj.indirizzo, "Mailing_City": obj.citta, "Mailing_Zip": obj.cap})


def _esito_fase(voce):
    """(chiusa, vinta) di una voce del picklist Stage."""
    tipo = str(voce.get("forecast_type") or "").lower()
    categoria = str((voce.get("forecast_category") or {}).get("name") or "").lower()
    if "won" in tipo or categoria == "closed":
        return True, True
    if "lost" in tipo or categoria == "omitted":
        return True, False
    if tipo == "open" or categoria == "pipeline":
        return False, False
    nome = str(voce.get("actual_value") or "").lower()
    if nome.startswith("closed") or nome.startswith("chius"):
        return True, "won" in nome or "vint" in nome
    return False, False


def _corpo(r):
    if not r.content:
        return {}
    try:
        corpo = r.json()
    except ValueError:
        return {}
    return corpo if isinstance(corpo, dict) else {}
