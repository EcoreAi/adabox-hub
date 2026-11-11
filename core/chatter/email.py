"""Email in uscita del chatter: un messaggio (non una nota) arriva ai follower, escluso l'autore."""
import logging
import re
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils.crypto import constant_time_compare, salted_hmac

from core import lavori
from core.models import Messaggio

SALE = "core.chatter.risposta"
log = logging.getLogger("core.chatter")
_INVII = []          # funzioni (messaggio, email) -> True se hanno spedito loro l'email a un esterno


def registra_invio(funzione):
    """Un'app spedisce da sé le email del chatter verso gli esterni (es. dalla casella dell'autore, modulo Posta).
    La funzione riceve il Messaggio e l'EmailMultiAlternatives pronta e restituisce True se l'ha spedita; se
    restituisce False o va in errore, parte dal server come sempre."""
    if funzione not in _INVII:
        _INVII.append(funzione)
    return funzione


def _spedisci_esterna(messaggio, email):
    for funzione in _INVII:
        try:
            if funzione(messaggio, email):
                return
        except Exception:
            log.exception("invio esterno del messaggio %s non riuscito: parte dal server", messaggio.pk)
    email.send()
TOKEN_RE = re.compile(r"^(\d+)-(\d+)-([0-9a-f]{16})$")


def host():
    return urlparse(settings.SITO_URL).hostname or "localhost"


def token_risposta(ct, pk):
    """Token per l'indirizzo di risposta: solo minuscole e cifre (sta nella parte locale dell'email)."""
    firma = salted_hmac(SALE, f"{ct}-{pk}").hexdigest()[:16]
    return f"{ct}-{pk}-{firma}"


def leggi_token(token):
    """(ct, pk) se il token è autentico, altrimenti None."""
    trovato = TOKEN_RE.match(token or "")
    if not trovato:
        return None
    ct, pk, _ = trovato.groups()
    if not constant_time_compare(token_risposta(ct, pk), token):
        return None
    return int(ct), int(pk)


def indirizzo_risposta(ct, pk):
    if not settings.EMAIL_RISPOSTE or "@" not in settings.EMAIL_RISPOSTE:
        return None
    locale, dominio = settings.EMAIL_RISPOSTE.rsplit("@", 1)
    return f"{locale}+{token_risposta(ct, pk)}@{dominio}"


def riferimento_record(ct, pk):
    """Message-ID fittizio del filo del record: in References raggruppa le email nei client di posta."""
    return f"<rec-{ct}-{pk}@{host()}>"


def destinatari(messaggio):
    from . import follower_di
    return [u for u in follower_di(messaggio.record).filter(is_active=True).exclude(email="")
            if u.pk != messaggio.autore_id]


def esterni(messaggio):
    """Indirizzi esterni del record (ModelView.destinatari_esterni), escluso chi ha scritto e chi è già utente."""
    from core.viste import registry
    obj = messaggio.record
    vista = registry.per_modello(type(obj)) if obj is not None else None
    if vista is None:
        return []
    utenti = {u.email.lower() for u in destinatari(messaggio)}
    visti, risultato = {messaggio.autore_email.lower(), ""}, []
    if messaggio.autore is not None and messaggio.autore.email:
        visti.add(messaggio.autore.email.lower())
    for indirizzo in [*vista.destinatari_esterni(obj), *(messaggio.destinatari or [])]:
        chiave = (indirizzo or "").strip().lower()
        if chiave not in visti and chiave not in utenti:
            visti.add(chiave)
            risultato.append(indirizzo.strip())
    return risultato


def accoda_notifica(messaggio):
    if messaggio.record is not None and (destinatari(messaggio) or esterni(messaggio)):
        return lavori.accoda("core.chatter.email.notifica", messaggio_id=messaggio.pk)
    return None


def accoda_menzioni(messaggio):
    """Chi è menzionato con @username riceve un'email. Con Discuss attivo no: lì la menzione arriva nella posta in
    arrivo, e per email solo se resta non letta (discuss.notifiche)."""
    from django.apps import apps

    from core.registry import modules

    from . import menzionati
    if apps.is_installed("discuss") and "discuss" not in modules.disattivati():
        return None
    if messaggio.record is not None and any(u.pk != messaggio.autore_id for u in menzionati(messaggio.corpo)):
        return lavori.accoda("core.chatter.email.menzioni", messaggio_id=messaggio.pk)
    return None


def menzioni(messaggio_id):
    """Lavoro: avvisa per email chi è menzionato nel messaggio o nella nota e può vedere il record."""
    from . import menzionati, puo_vedere
    m = Messaggio.objects.select_related("autore").get(pk=messaggio_id)
    obj = m.record
    if obj is None:
        return 0
    brand = settings.THEME.get("brand", "")
    autore = (m.autore.get_full_name() or m.autore.username) if m.autore else (m.autore_email or "Qualcuno")
    ctx = {"m": m, "obj": obj, "link": _link(obj), "brand": brand, "autore": autore, "menzione": True}
    inviate = 0
    with get_connection() as connessione:
        for u in menzionati(m.corpo):
            if u.pk == m.autore_id or not u.email or not puo_vedere(u, obj):
                continue
            email = EmailMultiAlternatives(
                subject=f"[{brand}] {autore} ti ha menzionato su {obj}",
                body=render_to_string("core/email/notifica.txt", {**ctx, "utente": u}), to=[u.email],
                connection=connessione)
            email.attach_alternative(render_to_string("core/email/notifica.html", {**ctx, "utente": u}), "text/html")
            email.send()
            inviate += 1
    return inviate


MAX_ALLEGATI = 15 * 1024 * 1024          # oltre, chi è esterno riceve solo i nomi dei file


def _allega(email, messaggio):
    """I file del messaggio vanno davvero a chi è esterno (non ha accesso all'applicazione), entro MAX_ALLEGATI."""
    file = list(messaggio.allegati.all())
    if not file or sum(a.dimensione for a in file) > MAX_ALLEGATI:
        return
    for a in file:
        with a.file.open("rb") as f:
            email.attach(a.nome, f.read())


def _link(obj):
    from core.viste import registry
    vista = registry.per_modello(type(obj))
    try:
        return settings.SITO_URL + vista.url("dettaglio", pk=obj.pk) if vista else settings.SITO_URL
    except Exception:
        return settings.SITO_URL


def notifica(messaggio_id):
    """Lavoro: invia il messaggio ai follower. Restituisce il numero di email inviate."""
    m = Messaggio.objects.select_related("autore", "content_type").get(pk=messaggio_id)
    obj = m.record
    if obj is None or m.tipo != Messaggio.MESSAGGIO:
        return 0
    if not m.message_id:
        m.message_id = f"<msg-{m.pk}-{uuid.uuid4().hex[:12]}@{host()}>"
        m.save(update_fields=["message_id"])
    brand = settings.THEME.get("brand", "")
    if m.autore:
        nome_autore = m.autore.get_full_name() or m.autore.username
    else:
        nome_autore = m.autore_email or "Sistema"
    ctx = {"m": m, "obj": obj, "link": _link(obj), "brand": brand, "autore": nome_autore}
    intestazioni = {"Message-ID": m.message_id, "References": riferimento_record(m.content_type_id, m.object_id)}
    risposta = indirizzo_risposta(m.content_type_id, m.object_id)
    inviate = 0
    with get_connection() as connessione:
        for u in destinatari(m):
            email = EmailMultiAlternatives(
                subject=f"[{brand}] {obj}", body=render_to_string("core/email/notifica.txt", {**ctx, "utente": u}),
                to=[u.email], headers=intestazioni, reply_to=[risposta] if risposta else None, connection=connessione)
            email.attach_alternative(render_to_string("core/email/notifica.html", {**ctx, "utente": u}), "text/html")
            email.send()
            inviate += 1
        for indirizzo in esterni(m):                     # clienti esterni: niente link all'applicazione
            ctx_esterno = {**ctx, "utente": None, "link": None, "esterno": True}
            email = EmailMultiAlternatives(
                subject=f"[{brand}] {obj}", body=render_to_string("core/email/notifica.txt", ctx_esterno),
                to=[indirizzo], headers=intestazioni, reply_to=[risposta] if risposta else None, connection=connessione)
            email.attach_alternative(render_to_string("core/email/notifica.html", ctx_esterno), "text/html")
            _allega(email, m)
            _spedisci_esterna(m, email)
            inviate += 1
    return inviate
