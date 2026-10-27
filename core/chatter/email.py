"""Email in uscita del chatter: un messaggio (non una nota) arriva ai follower, escluso l'autore."""
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


def accoda_notifica(messaggio):
    if messaggio.record is not None and destinatari(messaggio):
        return lavori.accoda("core.chatter.email.notifica", messaggio_id=messaggio.pk)
    return None


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
    ctx = {"m": m, "obj": obj, "link": _link(obj), "brand": brand,
           "autore": (m.autore.get_full_name() or m.autore.username) if m.autore else "Sistema"}
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
    return inviate
