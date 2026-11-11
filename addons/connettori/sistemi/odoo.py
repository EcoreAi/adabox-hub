"""Odoo (17, 18, 19): contatti (res.partner, persone e aziende) e opportunità (crm.lead), con una chiave API.

Documentazione: odoo.com, External API e JSON-2 (19.0). Con la 19 si chiama `POST /json/2/<modello>/<metodo>` con
`Authorization: bearer <chiave>` e `X-Odoo-Database`; la risposta è il valore JSON del metodo, gli errori hanno lo
stato HTTP e {"name": eccezione di Odoo, "message"}. Le API XML-RPC e JSON-RPC sono deprecate dalla 19.

Ogni chiamata gira con l'utente della chiave e le sue regole di Odoo: con una chiave per utente (collegamento «ogni
utente con la sua chiave») arriva solo ciò che quell'utente vede. Accorgimenti verificati su un Odoo 19 vero:
- le persone ereditano la partita IVA della loro azienda: la chiave è la partita IVA del partner commerciale;
- gli utenti di Odoo e le aziende dell'istanza sono anch'essi contatti: non si importano come clienti;
- le opportunità perse sono archiviate: si leggono con active_test spento e `won_status` dice vinta, persa o aperta;
- `mobile` non c'è più nella 19; il codice fiscale c'è con la localizzazione italiana (l10n_it_codice_fiscale)."""
import datetime

import httpx2 as httpx
from django.utils.dateparse import parse_datetime

from .base import (AZIENDE, OPPORTUNITA, PERSONE, ErroreConnettore, ErroreTemporaneo, Sistema, data, dominio, nazione, pieni,
                   pulisci)
from .hubspot import importo

PER_PAGINA = 200
TEMPO = 30
MODELLI = {PERSONE: "res.partner", AZIENDE: "res.partner", OPPORTUNITA: "crm.lead"}
CAMPI = {
    PERSONE: ["name", "email", "phone", "function", "street", "city", "zip", "country_code", "website", "parent_id",
              "commercial_partner_id", "is_company", "write_date"],
    AZIENDE: ["name", "email", "phone", "street", "city", "zip", "country_code", "website", "vat", "l10n_it_codice_fiscale",
              "is_company", "write_date"],
    OPPORTUNITA: ["name", "expected_revenue", "date_deadline", "stage_id", "won_status", "active", "probability", "partner_id",
                  "commercial_partner_id", "user_id", "description", "write_date"],
}
PERSA = {"id": "__persa__", "label": "Persa", "ordine": 10_000, "probabilita": 0.0, "chiusa": True, "vinta": False}


def _quando(istante):
    """Le date di Odoo sono in UTC senza fuso: «2026-11-11 12:44:22»."""
    return istante.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _id(valore):
    """[id, "nome"] dei many2one → id; False → None."""
    return valore[0] if isinstance(valore, (list, tuple)) and valore else None


class Odoo(Sistema):
    nome, etichetta = "odoo", "Odoo"

    def __init__(self, url, database, chiave, transport=None):
        self.url = (url or "").rstrip("/")
        intestazioni = {"Authorization": f"bearer {chiave}", "Content-Type": "application/json"}
        if database:
            intestazioni["X-Odoo-Database"] = database
        self.http = httpx.Client(base_url=self.url, timeout=TEMPO, transport=transport, trust_env=False, follow_redirects=False,
                                 headers=intestazioni)
        self._campi, self._esclusi = {}, None

    def _chiama(self, modello, metodo, **argomenti):
        try:
            r = self.http.post(f"/json/2/{modello}/{metodo}", json=argomenti)
        except httpx.HTTPError as e:
            raise ErroreTemporaneo(f"Odoo non raggiungibile: {type(e).__name__}") from e
        if r.status_code == 200:
            return r.json()
        try:
            corpo = r.json()
        except ValueError:
            corpo = {}
        nome, messaggio = str(corpo.get("name") or ""), str(corpo.get("message") or "").split("\n")[0][:200]
        if r.status_code in (429, 502, 503, 504) or "SerializationFailure" in nome or "concurrent" in messaggio.lower():
            raise ErroreTemporaneo(f"Odoo risponde {r.status_code}: si riprova più tardi")
        if r.status_code == 401:
            raise ErroreConnettore("Odoo rifiuta la chiave API: controlla che sia valida e non scaduta (Preferenze → Sicurezza dell'account).")
        if r.status_code == 404:
            raise ErroreConnettore(f"Odoo non conosce {modello}.{metodo}: serve Odoo 19 con l'app installata (CRM per le opportunità).")
        if "AccessError" in nome:
            raise ErroreConnettore(f"Odoo nega l'accesso: {messaggio}")
        raise ErroreConnettore(f"Odoo risponde {r.status_code}: {messaggio or nome}")

    def verifica(self):
        return self.utente()

    def utente(self):
        """L'id dell'utente della chiave in Odoo."""
        return str(self._chiama("res.users", "context_get").get("uid") or "")

    # --- campi e filtri ----------------------------------------------------------------------------------------------

    def _campi_di(self, tipo):
        """I campi richiesti che questo Odoo ha (il codice fiscale c'è solo con la localizzazione italiana)."""
        modello = MODELLI[tipo]
        if modello not in self._campi:
            self._campi[modello] = set(self._chiama(modello, "fields_get", attributes=["type"]))
        return [c for c in CAMPI[tipo] if c in self._campi[modello]]

    def _filtro(self, tipo):
        if tipo == OPPORTUNITA:
            return [["type", "=", "opportunity"]]
        if self._esclusi is None:                         # i contatti delle aziende dell'istanza non sono clienti
            self._esclusi = [_id(c["partner_id"]) for c in self._chiama("res.company", "search_read", domain=[], fields=["partner_id"])]
        return [["is_company", "=", tipo == AZIENDE], ["user_ids", "=", False], ["id", "not in", [i for i in self._esclusi if i]]]

    def _contesto(self, tipo):
        return {"active_test": False} if tipo == OPPORTUNITA else {}

    # --- lettura ---------------------------------------------------------------------------------------------------------

    def modificati(self, tipo, da, dopo=None):
        inizio = int(dopo or 0)
        record = self._chiama(MODELLI[tipo], "search_read", domain=[*self._filtro(tipo), ["write_date", ">=", _quando(da)]],
                              fields=self._campi_di(tipo), order="write_date asc, id asc", limit=PER_PAGINA, offset=inizio,
                              context=self._contesto(tipo))
        return [{**r, "id": str(r["id"])} for r in record], (str(inizio + PER_PAGINA) if len(record) == PER_PAGINA else None)

    def istante(self, tipo, record):
        valore = parse_datetime(str(record.get("write_date") or ""))
        return valore.replace(tzinfo=datetime.timezone.utc) if valore is not None and valore.tzinfo is None else valore

    def ids_visibili(self, tipo):
        """Tutti gli id del tipo che l'utente della chiave vede adesso (per la visibilità in adabox)."""
        return {str(i) for i in self._chiama(MODELLI[tipo], "search", domain=self._filtro(tipo), context=self._contesto(tipo))}

    def associazioni(self, tipo, verso, record):
        voci = {}
        for r in record:
            if verso == AZIENDE:
                azienda = _id(r.get("commercial_partner_id")) if tipo == OPPORTUNITA else _id(r.get("parent_id"))
                if tipo == PERSONE and azienda is None and _id(r.get("commercial_partner_id")) not in (None, int(r["id"])):
                    azienda = _id(r.get("commercial_partner_id"))
                if azienda is not None and str(azienda) != r["id"]:
                    voci[r["id"]] = [str(azienda)]
            elif tipo == OPPORTUNITA and verso == PERSONE:
                persona, azienda = _id(r.get("partner_id")), _id(r.get("commercial_partner_id"))
                if persona is not None and persona != azienda:
                    voci[r["id"]] = [str(persona)]
        return voci

    def trova(self, tipo, chiave, valore):
        filtro = {"email": [["email", "=ilike", valore]], "nome": [["name", "=ilike", valore]], "piva": [["vat", "=ilike", valore]],
                  "dominio": [["website", "ilike", valore]]}[chiave]
        voci = self._chiama(MODELLI[tipo], "search_read", domain=[*self._filtro(tipo), *filtro], fields=["website"], limit=20)
        if chiave == "dominio":
            voci = [v for v in voci if dominio(v.get("website")) == valore]
        return str(voci[0]["id"]) if len(voci) == 1 else (None if not voci else False)

    # --- scrittura -------------------------------------------------------------------------------------------------------

    def crea(self, tipo, dati):
        if tipo == AZIENDE:
            dati = {**dati, "is_company": True}
        if tipo == OPPORTUNITA:
            dati = {**dati, "type": "opportunity"}
        return str(self._chiama(MODELLI[tipo], "create", vals_list=[dati])[0])

    def aggiorna(self, tipo, id_esterno, dati):
        self._chiama(MODELLI[tipo], "write", ids=[int(id_esterno)], vals=dati)

    def associa(self, tipo, id_esterno, verso, id_verso):
        campo = "parent_id" if tipo == PERSONE else "partner_id"
        self.aggiorna(tipo, id_esterno, {campo: int(id_verso)})

    # --- fasi ------------------------------------------------------------------------------------------------------------

    def fasi(self):
        """Le fasi del CRM (crm.stage); la vittoria è la fase con is_won. Persa non è una fase in Odoo (l'opportunità si
        archivia con won_status «lost»): la rappresenta PERSA."""
        voci = sorted(self._chiama("crm.stage", "search_read", domain=[], fields=["name", "sequence", "is_won"]), key=lambda f: (f["sequence"], f["id"]))
        aperte = [f for f in voci if not f["is_won"]]
        fasi = [{"id": str(f["id"]), "label": f["name"], "ordine": f["sequence"], "chiusa": bool(f["is_won"]), "vinta": bool(f["is_won"]),
                 "probabilita": 1.0 if f["is_won"] else round((aperte.index(f) + 1) / (len(aperte) + 1), 2)} for f in voci]
        return fasi + [PERSA]

    # --- i campi -----------------------------------------------------------------------------------------------------

    def in_adabox(self, tipo, r, fasi=None):
        r = {k: (None if v is False else v) for k, v in r.items()}          # in Odoo un campo vuoto vale False
        if tipo == OPPORTUNITA:
            dati = {}
            if str(r.get("name") or "").strip():
                dati["titolo"] = str(r["name"]).strip()[:200]
            if (valore := importo(r.get("expected_revenue"))) is not None and valore:
                dati["valore_atteso"] = valore
            if giorno := data(r.get("date_deadline")):
                dati["chiusura_prevista"] = giorno
            stato = r.get("won_status")
            if stato == "lost" or (stato is None and r.get("active") is False and not r.get("probability")):
                dati["fase_esterna"] = PERSA
            elif fase := next((f for f in fasi or [] if f["id"] == str(_id(r.get("stage_id")))), None):
                dati["fase_esterna"] = fase
            if _id(r.get("user_id")) is not None:
                dati["utente_esterno"] = str(_id(r["user_id"]))
            return dati
        comuni = {"nome": r.get("name"), "telefono": r.get("phone"), "indirizzo": r.get("street"), "citta": r.get("city"), "cap": r.get("zip"),
                  "sito": r.get("website"), "nazione": nazione(r.get("country_code"))}
        if tipo == AZIENDE:
            return pulisci({**comuni, "email": str(r.get("email") or "").lower(), "partita_iva": r.get("vat"),
                            "codice_fiscale": r.get("l10n_it_codice_fiscale")})
        return pulisci({**comuni, "email": str(r.get("email") or "").lower(), "ruolo": r.get("function")})

    def fuori(self, tipo, obj, fase=None):
        if tipo == OPPORTUNITA:
            dati = pieni({"name": obj.titolo, "expected_revenue": float(obj.valore_atteso) if obj.valore_atteso else None,
                          "date_deadline": obj.chiusura_prevista.isoformat() if obj.chiusura_prevista else None})
            if fase is not None and fase["id"] != PERSA["id"]:
                dati["stage_id"] = int(fase["id"])
            return dati
        dati = {"name": obj.nome, "email": obj.email, "phone": obj.telefono, "street": obj.indirizzo, "city": obj.citta, "zip": obj.cap,
                "website": obj.sito}
        if tipo == AZIENDE:
            dati["vat"] = obj.partita_iva
        else:
            dati["function"] = obj.ruolo
        return pieni(dati)

