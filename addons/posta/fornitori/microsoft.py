"""Microsoft 365 e Outlook.com: posta e calendario con Microsoft Graph, con un'app registrata su Microsoft Entra
(piattaforma «Web», un segreto client).

Documentazione: learn.microsoft.com, identity platform (authorization code flow), Graph /me/messages
($filter su receivedDateTime, /$value per il MIME) e /me/events (lastModifiedDateTime, Prefer: outlook.timezone).
Il refresh token cambia a ogni rinnovo: si salva quello nuovo. Gli eventi ricorrenti (seriesMaster) e annullati non
passano."""
import base64
import datetime
from urllib.parse import urlsplit

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .base import ErrorePosta, Fornitore, affermazioni, mezzanotte

GRAPH = "https://graph.microsoft.com/v1.0"
PER_PAGINA = 50
UTC = {"Prefer": 'outlook.timezone="UTC", outlook.body-content-type="text"'}


def _iso(istante):
    return istante.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pagina_graph(url):
    """Le pagine successive restano su Graph: il token non va mandato altrove."""
    parti = urlsplit(url or "")
    if parti.scheme != "https" or parti.hostname != "graph.microsoft.com":
        raise ErrorePosta("Pagina successiva di Microsoft non valida.")
    return url


class Microsoft(Fornitore):
    tipo, etichetta = "microsoft", "Microsoft"
    AMBITO_INVIO = "Mail.Send"
    AMBITI = ("openid", "email", "offline_access", "User.Read", "Mail.Read", AMBITO_INVIO, "Calendars.ReadWrite")

    @property
    def _base(self):
        tenant = (self.servizio.tenant or "common").strip() or "common"
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"

    @property
    def AUTORIZZA(self):
        return f"{self._base}/authorize"

    @property
    def TOKEN(self):
        return f"{self._base}/token"

    def parametri_autorizzazione(self):
        return {"response_mode": "query", "prompt": "select_account"}

    def indirizzo(self, corpo):
        me = self._chiama("GET", f"{GRAPH}/me", params={"$select": "mail,userPrincipalName"}).json()
        email = str(me.get("mail") or me.get("userPrincipalName") or affermazioni(corpo.get("id_token")).get("email") or "").lower()
        if "@" not in email:
            raise ErrorePosta("Microsoft non ha detto l'indirizzo della casella: riprova.")
        return email

    # --- posta ---------------------------------------------------------------------------------------------------------

    def messaggi(self, dal, dopo=None):
        if dopo:
            dati = self._chiama("GET", _pagina_graph(dopo)).json()
        else:
            dati = self._chiama("GET", f"{GRAPH}/me/messages", params={
                "$filter": f"receivedDateTime ge {_iso(dal)} and isDraft eq false", "$orderby": "receivedDateTime asc", "$top": PER_PAGINA,
                "$select": "id,receivedDateTime,from,toRecipients,ccRecipients"}).json()
        voci = []
        for m in dati.get("value", []):
            persone = [m.get("from")] + (m.get("toRecipients") or []) + (m.get("ccRecipients") or [])
            indirizzi = [str((p or {}).get("emailAddress", {}).get("address") or "").lower() for p in persone]
            voci.append({"id": m["id"], "indirizzi": [e for e in indirizzi if e], "quando": parse_datetime(m.get("receivedDateTime") or "")})
        return voci, dati.get("@odata.nextLink")

    def grezza(self, id_esterno):
        return self._chiama("GET", f"{GRAPH}/me/messages/{id_esterno}/$value").content

    def invia(self, grezza):
        """sendMail accetta il MIME in base64 con Content-Type text/plain; la copia va negli elementi inviati."""
        self._chiama("POST", f"{GRAPH}/me/sendMail", content=base64.b64encode(grezza), headers={"Content-Type": "text/plain"})

    # --- calendario ----------------------------------------------------------------------------------------------------

    def eventi(self, dal, dopo=None):
        if dopo:
            dati = self._chiama("GET", _pagina_graph(dopo), headers=UTC).json()
        else:
            dati = self._chiama("GET", f"{GRAPH}/me/events", headers=UTC, params={
                "$filter": f"lastModifiedDateTime ge {_iso(dal)}", "$orderby": "lastModifiedDateTime asc", "$top": PER_PAGINA,
                "$select": "id,subject,body,start,end,isAllDay,location,attendees,type,isCancelled,lastModifiedDateTime"}).json()
        return [_evento(e) for e in dati.get("value", [])], dati.get("@odata.nextLink")

    def crea_evento(self, dati):
        return self._chiama("POST", f"{GRAPH}/me/events", json=_fuori(dati)).json()["id"]

    def aggiorna_evento(self, id_esterno, dati):
        self._chiama("PATCH", f"{GRAPH}/me/events/{id_esterno}", json=_fuori(dati))


def _utc(valore):
    """{"dateTime": "2026-11-10T09:00:00.0000000", "timeZone": "UTC"} → datetime in UTC."""
    testo = str((valore or {}).get("dateTime") or "")[:19]
    try:
        return datetime.datetime.fromisoformat(testo).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def _evento(e):
    inizio, fine, tutto = _utc(e.get("start")), _utc(e.get("end")), bool(e.get("isAllDay"))
    if tutto and inizio is not None:              # la giornata intera può tornare alle 23:00 o 22:00 UTC del giorno prima
        primo = (inizio + datetime.timedelta(hours=12)).date()
        dopo = (fine + datetime.timedelta(hours=12)).date() if fine else primo + datetime.timedelta(days=1)
        inizio, fine = mezzanotte(primo), mezzanotte(max(primo, dopo - datetime.timedelta(days=1)))
    corpo = e.get("body") or {}
    return {"id": e["id"], "titolo": (e.get("subject") or "(senza titolo)")[:200], "inizio": inizio, "fine": fine or inizio,
            "tutto_il_giorno": tutto, "luogo": str((e.get("location") or {}).get("displayName") or "")[:200],
            "descrizione": corpo.get("content", "") if corpo.get("contentType", "text") == "text" else "",
            "partecipanti": [str(p.get("emailAddress", {}).get("address") or "").lower() for p in e.get("attendees") or []
                             if p.get("emailAddress", {}).get("address")],
            "aggiornato": parse_datetime(e.get("lastModifiedDateTime") or ""),
            "saltare": bool(e.get("isCancelled")) or e.get("type") in ("seriesMaster", "occurrence", "exception") or inizio is None}


def _fuori(d):
    if d["tutto_il_giorno"]:
        inizio = timezone.localtime(d["inizio"]).date()
        fine = timezone.localtime(d["fine"]).date() + datetime.timedelta(days=1)
        quando = {"start": {"dateTime": f"{inizio.isoformat()}T00:00:00", "timeZone": "UTC"},
                  "end": {"dateTime": f"{fine.isoformat()}T00:00:00", "timeZone": "UTC"}, "isAllDay": True}
    else:
        quando = {"start": {"dateTime": d["inizio"].astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
                  "end": {"dateTime": d["fine"].astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
                  "isAllDay": False}
    return {"subject": d["titolo"], "body": {"contentType": "text", "content": d["descrizione"]}, "location": {"displayName": d["luogo"]},
            **quando}
