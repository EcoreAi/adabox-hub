"""Google: Gmail (lettura) e Google Calendar (eventi del calendario principale), con un client OAuth «Applicazione
web» di Google Cloud.

Documentazione: developers.google.com/identity/protocols/oauth2/web-server, Gmail API users.messages (q
«after:<secondi>», format=raw), Calendar API events (updatedMin, orderBy=updated). L'accesso permanente arriva solo
con access_type=offline e prompt=consent. gmail.readonly è un ambito «riservato»: per account fuori dalla propria
organizzazione Google chiede la verifica dell'app."""
import base64
import datetime
from email.utils import getaddresses

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .base import ErrorePosta, Fornitore, affermazioni, mezzanotte

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDARIO = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
PER_PAGINA = 100


def _rfc3339(istante):
    return istante.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Google(Fornitore):
    tipo, etichetta = "google", "Google"
    AUTORIZZA = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN = "https://oauth2.googleapis.com/token"
    AMBITI = ("openid", "email", "https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/calendar.events")

    def parametri_autorizzazione(self):
        return {"access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}

    def indirizzo(self, corpo):
        email = str(affermazioni(corpo.get("id_token")).get("email") or "").lower()
        if not email:
            raise ErrorePosta("Google non ha detto l'indirizzo della casella: riprova.")
        return email

    # --- posta ---------------------------------------------------------------------------------------------------------

    def messaggi(self, dal, dopo=None):
        """Gmail elenca dal più recente e senza intestazioni: per ogni messaggio si leggono solo mittente e
        destinatari (format=metadata); il messaggio intero si scarica solo se c'è un contatto."""
        parametri = {"q": f"after:{int(dal.timestamp())}", "maxResults": PER_PAGINA}
        if dopo:
            parametri["pageToken"] = dopo
        dati = self._chiama("GET", f"{GMAIL}/messages", params=parametri).json()
        voci = []
        for m in dati.get("messages", []):
            meta = self._chiama("GET", f"{GMAIL}/messages/{m['id']}", params=[("format", "metadata"), ("metadataHeaders", "From"),
                                                                             ("metadataHeaders", "To"), ("metadataHeaders", "Cc")]).json()
            if set(meta.get("labelIds") or []) & {"SPAM", "TRASH", "DRAFT", "CHAT"}:
                continue
            intestazioni = [h.get("value", "") for h in (meta.get("payload") or {}).get("headers", [])]
            quando = datetime.datetime.fromtimestamp(int(meta.get("internalDate") or 0) / 1000, tz=datetime.timezone.utc)
            voci.append({"id": m["id"], "indirizzi": [e.lower() for _, e in getaddresses(intestazioni) if e], "quando": quando})
        return voci, dati.get("nextPageToken")

    def grezza(self, id_esterno):
        dati = self._chiama("GET", f"{GMAIL}/messages/{id_esterno}", params={"format": "raw"}).json()
        raw = dati.get("raw") or ""
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))

    # --- calendario ----------------------------------------------------------------------------------------------------

    def eventi(self, dal, dopo=None):
        parametri = {"updatedMin": _rfc3339(dal), "orderBy": "updated", "showDeleted": "false", "singleEvents": "false", "maxResults": 250}
        if dopo:
            parametri["pageToken"] = dopo
        dati = self._chiama("GET", CALENDARIO, params=parametri).json()
        return [_evento(e) for e in dati.get("items", [])], dati.get("nextPageToken")

    def crea_evento(self, dati):
        return self._chiama("POST", CALENDARIO, json=_fuori(dati)).json()["id"]

    def aggiorna_evento(self, id_esterno, dati):
        self._chiama("PATCH", f"{CALENDARIO}/{id_esterno}", json=_fuori(dati))


def _quando(valore):
    """(datetime, giornata intera) da {"dateTime"} o {"date"}."""
    valore = valore or {}
    if valore.get("date"):
        return mezzanotte(datetime.date.fromisoformat(valore["date"])), True
    return parse_datetime(valore.get("dateTime") or ""), False


def _evento(e):
    inizio, tutto = _quando(e.get("start"))
    fine, _ = _quando(e.get("end"))
    if tutto and fine is not None:
        fine -= datetime.timedelta(days=1)            # su Google la fine di una giornata intera è il giorno dopo
    return {"id": e["id"], "titolo": (e.get("summary") or "(senza titolo)")[:200], "inizio": inizio, "fine": fine or inizio,
            "tutto_il_giorno": tutto, "luogo": (e.get("location") or "")[:200], "descrizione": e.get("description") or "",
            "partecipanti": [str(p.get("email", "")).lower() for p in e.get("attendees") or [] if p.get("email")],
            "aggiornato": parse_datetime(e.get("updated") or ""),
            "saltare": e.get("status") == "cancelled" or bool(e.get("recurrence")) or bool(e.get("recurringEventId")) or inizio is None}


def _fuori(d):
    if d["tutto_il_giorno"]:
        inizio, fine = timezone.localtime(d["inizio"]).date(), timezone.localtime(d["fine"]).date() + datetime.timedelta(days=1)
        quando = {"start": {"date": inizio.isoformat()}, "end": {"date": fine.isoformat()}}
    else:
        quando = {"start": {"dateTime": d["inizio"].isoformat()}, "end": {"dateTime": d["fine"].isoformat()}}
    return {"summary": d["titolo"], "location": d["luogo"], "description": d["descrizione"], **quando}
