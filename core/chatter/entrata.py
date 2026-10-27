"""Email in entrata: chi risponde a una notifica scrive nel chatter del record."""
import email
import hashlib
import html
import imaplib
import logging
import re
import traceback
from email import policy
from email.utils import getaddresses, parseaddr
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.html import strip_tags

from core import allegati, azienda
from core.models import EmailRicevuta, Messaggio
from core.viste import registry

from . import email as posta
from . import scrivi

log = logging.getLogger("core.chatter")
_GESTORI = []          # funzioni (msg, mittente) -> record o None, per le email non abbinate


def registra_gestore(funzione):
    """Un'app gestisce le email che non rispondono a nessun record (es. l'helpdesk apre un ticket).
    La funzione riceve il messaggio email e il mittente e restituisce il record creato, o None."""
    if funzione not in _GESTORI:
        _GESTORI.append(funzione)
    return funzione


def svuota_gestori():
    """Solo per i test."""
    _GESTORI.clear()


def esterno_ammesso(obj, mittente):
    vista = registry.per_modello(type(obj))
    ammessi = {e.strip().lower() for e in (vista.destinatari_esterni(obj) if vista else []) if e}
    return mittente.lower() in ammessi
CITAZIONE_RE = re.compile(r"(ha scritto|wrote)\s*:\s*$", re.I)
SEPARATORI = ("-----original message-----", "-----messaggio originale-----", "________________________________")


def togli_citazione(testo):
    """Il testo nuovo della risposta: si taglia alla riga "Il … ha scritto:" / "On … wrote:", ai separatori
    dei client e alle righe citate con '>'."""
    righe = testo.replace("\r\n", "\n").split("\n")
    tenute = []
    for i, riga in enumerate(righe):
        pulita = riga.strip()
        if pulita.startswith(">") or pulita.lower() in SEPARATORI:
            break
        if CITAZIONE_RE.search(pulita):
            if not re.match(r"^(il|on)\b", pulita, re.I) and tenute and re.match(r"^(il|on)\b", tenute[-1].strip(), re.I):
                tenute.pop()                   # intestazione della citazione andata a capo
            break
        tenute.append(riga)
    return "\n".join(tenute).strip()


def _testo(msg):
    parte = msg.get_body(preferencelist=("plain", "html"))
    if parte is None:
        return ""
    contenuto = parte.get_content()
    if parte.get_content_type() == "text/html":
        contenuto = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", contenuto)
        contenuto = html.unescape(strip_tags(contenuto))
    return contenuto


def _abbina(msg):
    """(content_type_id, pk) dal Message-ID di un nostro messaggio citato o dal token firmato nell'indirizzo."""
    riferimenti = re.findall(r"<[^>]+>", f"{msg.get('In-Reply-To', '')} {msg.get('References', '')}")
    if riferimenti:
        m = Messaggio.objects.filter(message_id__in=riferimenti).order_by("-pk").first()
        if m is not None:
            return m.content_type_id, m.object_id
    intestazioni = [str(v) for h in ("To", "Cc", "Delivered-To", "X-Original-To") for v in (msg.get_all(h) or [])]
    for _, indirizzo in getaddresses(intestazioni):
        locale = indirizzo.split("@")[0]
        if "+" in locale and (trovato := posta.leggi_token(locale.split("+", 1)[1].lower())):
            return trovato
    return None


def _autore(mittente, modello, pk):
    """L'utente attivo con quell'email che può vedere il record (nell'azienda del record), o None."""
    vista = registry.per_modello(modello)
    obj = modello._default_manager.filter(pk=pk).first() if vista else None
    if obj is None:
        return None, None
    azienda_record = getattr(obj, vista.company_field) if vista.company_field else None
    for u in get_user_model().objects.filter(email__iexact=mittente, is_active=True):
        consentite = azienda.consentite(u)
        if azienda_record is not None and azienda_record not in consentite:
            continue
        richiesta = SimpleNamespace(user=u, azienda=azienda_record or (consentite[0] if consentite else None))
        if vista.get_queryset(richiesta).filter(pk=pk).exists() and vista.has_view_permission(richiesta, obj):
            return u, obj
    return None, obj


def ricevi(grezza):
    """Elabora un'email (bytes). Idempotente sul Message-ID. Restituisce la riga EmailRicevuta."""
    msg = email.message_from_bytes(grezza, policy=policy.default)
    message_id = (str(msg.get("Message-ID") or "").strip()
                  or f"<senza-id-{hashlib.sha256(grezza).hexdigest()[:32]}@locale>")[:255]
    if (gia := EmailRicevuta.objects.filter(message_id=message_id).first()) is not None:
        return gia
    riga = EmailRicevuta(message_id=message_id, mittente=parseaddr(str(msg.get("From", "")))[1].lower()[:254],
                         oggetto=str(msg.get("Subject", ""))[:255])
    try:
        with transaction.atomic():
            _elabora(msg, riga)
    except Exception:
        log.exception("email %s non elaborata", message_id)
        riga.stato, riga.motivo, riga.messaggio = EmailRicevuta.ERRORE, traceback.format_exc()[-4000:], None
    riga.save()
    return riga


def _elabora(msg, riga):
    abbinamento = _abbina(msg)
    if abbinamento is None:
        obj = next((o for o in (g(msg, riga.mittente) for g in _GESTORI) if o is not None), None)
        if obj is None:
            riga.stato, riga.motivo = EmailRicevuta.NON_ABBINATA, "nessun riferimento a un record (Message-ID o token)"
            return
        abbinamento = (ContentType.objects.get_for_model(obj).pk, obj.pk)
    ct_id, pk = abbinamento
    modello = ContentType.objects.get_for_id(ct_id).model_class()
    riga.content_type_id, riga.object_id = ct_id, pk
    utente, obj = _autore(riga.mittente, modello, pk) if modello else (None, None)
    if obj is None:
        riga.stato, riga.motivo = EmailRicevuta.RIFIUTATA, "il record non esiste più"
        return
    if utente is None and not esterno_ammesso(obj, riga.mittente):
        riga.stato, riga.motivo = EmailRicevuta.RIFIUTATA, f"{riga.mittente} non è un utente che può vedere il record"
        return
    corpo, scartati, file = togli_citazione(_testo(msg)), [], []
    for parte in msg.iter_attachments():
        try:
            contenuto = ContentFile(parte.get_payload(decode=True) or b"", name=parte.get_filename() or "allegato")
            file.append(allegati.salva(obj, contenuto, utente))
        except allegati.AllegatoNonValido as e:
            scartati.append(str(e))
    if not corpo and not file:
        riga.stato, riga.motivo = EmailRicevuta.RIFIUTATA, "nessun testo né allegati"
        return
    riga.messaggio = scrivi(obj, utente, corpo, Messaggio.MESSAGGIO, allegati=file,
                            autore_email="" if utente else riga.mittente)
    riga.stato, riga.motivo = EmailRicevuta.ABBINATA, "; ".join(scartati)


def _connessione():
    u = urlparse(settings.IMAP_URL)
    sicura = u.scheme == "imaps"
    classe = imaplib.IMAP4_SSL if sicura else imaplib.IMAP4
    conn = classe(u.hostname, u.port or (993 if sicura else 143))
    conn.login(unquote(u.username or ""), unquote(u.password or ""))
    conn.select(unquote(u.path.lstrip("/")) or "INBOX")
    return conn


def leggi_casella():
    """Lavoro pianificato: elabora le email non lette della casella IMAP_URL. Senza IMAP_URL non fa nulla."""
    if not settings.IMAP_URL:
        return 0
    conn = _connessione()
    elaborate = 0
    try:
        _, dati = conn.search(None, "UNSEEN")
        for numero in (dati[0] or b"").split():
            _, parti = conn.fetch(numero, "(BODY.PEEK[])")
            ricevi(parti[0][1])
            conn.store(numero, "+FLAGS", "\\Seen")
            elaborate += 1
    finally:
        try:
            conn.close()
        finally:
            conn.logout()
    return elaborate
