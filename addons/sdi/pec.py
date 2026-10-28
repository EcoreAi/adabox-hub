"""Casella PEC: invio con SMTP e lettura con IMAP dei messaggi dello SDI (notifiche e fatture dei fornitori)."""
import email
import email.policy
import imaplib
import logging
import re
from urllib.parse import unquote, urlparse

from django.core.mail.backends.smtp import EmailBackend

from core import parametri
from core.models import Azienda

log = logging.getLogger("sdi.pec")
INDIRIZZO_SDI = re.compile(r"^sdi\d+@pec\.fatturapa\.it$", re.I)
SCARTATI = {"daticert.xml", "smime.p7s", "postacert.eml"}


def connessione_smtp(url):
    u = urlparse(url)
    return EmailBackend(host=u.hostname, port=u.port or (465 if u.scheme == "smtps" else 587),
                        username=unquote(u.username or ""), password=unquote(u.password or ""),
                        use_ssl=u.scheme == "smtps", use_tls=u.scheme == "smtp", timeout=60)


def _imap(url):
    u = urlparse(url)
    sicura = u.scheme == "imaps"
    conn = (imaplib.IMAP4_SSL if sicura else imaplib.IMAP4)(u.hostname, u.port or (993 if sicura else 143))
    conn.login(unquote(u.username or ""), unquote(u.password or ""))
    conn.select(unquote(u.path.lstrip("/")) or "INBOX")
    return conn


def file_del_messaggio(grezzo):
    """(mittente SDI o "", [(nome, bytes)]) dalla busta PEC: i file stanno nel messaggio originale allegato."""
    messaggio = email.message_from_bytes(grezzo, policy=email.policy.default)
    mittente, file = "", []
    for parte in messaggio.walk():
        if parte.get_content_type() == "message/rfc822" or parte.is_multipart():
            interno = parte.get("From")
            if interno:
                indirizzo = email.utils.parseaddr(str(interno))[1]
                if INDIRIZZO_SDI.match(indirizzo):
                    mittente = indirizzo
            continue
        nome = parte.get_filename()
        if nome and nome.lower() not in SCARTATI and nome.lower().endswith((".xml", ".p7m", ".zip")):
            file.append((nome, parte.get_payload(decode=True) or b""))
    da = email.utils.parseaddr(str(messaggio.get("From", "")))[1]
    if not mittente and INDIRIZZO_SDI.match(da):
        mittente = da
    return mittente, file


def elabora_messaggio(grezzo, azienda):
    from . import ricezione
    mittente, file = file_del_messaggio(grezzo)
    if mittente and mittente.lower() != (parametri.leggi("sdi.indirizzo_sdi", azienda) or "").lower():
        parametri.scrivi("sdi.indirizzo_sdi", mittente, azienda)     # lo SDI indica l'indirizzo da usare
    return [ricezione.ricevi(nome, contenuto, azienda) for nome, contenuto in file]


def leggi(azienda):
    url = parametri.leggi("sdi.pec_imap", azienda)
    if parametri.leggi("sdi.canale", azienda) != "pec" or not url:
        return 0
    conn = _imap(url)
    elaborati = 0
    try:
        _, dati = conn.search(None, "UNSEEN")
        for numero in (dati[0] or b"").split():
            _, parti = conn.fetch(numero, "(BODY.PEEK[])")
            try:
                elabora_messaggio(parti[0][1], azienda)
            except Exception:
                log.exception("PEC di %s: messaggio %s non elaborato", azienda, numero)
                continue                                    # resta non letto: si riprova al prossimo giro
            conn.store(numero, "+FLAGS", "\\Seen")
            elaborati += 1
    finally:
        try:
            conn.close()
        finally:
            conn.logout()
    return elaborati


def leggi_tutte():
    """Lavoro pianificato: la casella PEC di ogni azienda che usa il canale PEC."""
    totale = 0
    for azienda in Azienda.objects.filter(attiva=True):
        try:
            totale += leggi(azienda)
        except Exception:
            log.exception("PEC di %s non leggibile", azienda)
    return f"messaggi elaborati: {totale}"
