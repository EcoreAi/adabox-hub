"""Le email della casella nello storico dei clienti (CRM-08).

Di ogni messaggio si guardano prima solo mittente e destinatari: se tra loro c'è un contatto dell'azienda (escluse la
casella stessa e i colleghi), il messaggio si scarica e finisce nel chatter del contatto e, se ce n'è una sola, della
sua opportunità aperta. Le email senza contatti non si scaricano e non lasciano traccia. Nel chatter entra come
messaggio già avvenuto: non riparte per email ai follower. Il Message-ID resta sul messaggio, così una risposta che
torna dalla casella di sistema si abbina allo stesso record."""
import datetime
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models.functions import Lower
from django.utils import timezone

from core.generici import ct_di
from core.chatter.entrata import _testo, togli_citazione
from core.models import Messaggio

from .models import EmailSincronizzata

LUNGHEZZA = 20000


def indirizzi_interni():
    """Le email dei colleghi: una conversazione solo tra colleghi non è una conversazione con un cliente."""
    return {e.lower() for e in get_user_model().objects.filter(is_active=True).exclude(email="").values_list("email", flat=True)}


def contatti_tra(azienda, indirizzi):
    from contatti.models import Contatto
    if not indirizzi:
        return []
    return list(Contatto.objects.filter(azienda=azienda).annotate(e=Lower("email")).filter(e__in=sorted(indirizzi)).order_by("pk"))


def opportunita_aperta(contatti):
    """L'unica opportunità aperta dei contatti (o delle loro aziende); con più di una non si sceglie a caso."""
    if not apps.is_installed("crm") or not contatti:
        return None
    from crm.models import Opportunita
    clienti = {c.pk for c in contatti} | {c.societa_id for c in contatti if c.societa_id}
    aperte = list(Opportunita.objects.filter(contatto_id__in=clienti, stato=Opportunita.APERTA)[:2])
    return aperte[0] if len(aperte) == 1 else None


def _corpo(msg, allegati):
    oggetto = str(msg.get("Subject") or "").strip() or "(senza oggetto)"
    testo = togli_citazione(_testo(msg)) or "(nessun testo)"
    corpo = f"✉ {oggetto}\n\n{testo}"
    if allegati:
        corpo += f"\n\n({allegati} allegati restano nella casella)"
    return corpo[:LUNGHEZZA]


def importa(casella, voce, fornitore, interni=None):
    """Un messaggio elencato dal servizio: 'nessuno' (nessun contatto), 'gia' (già scritto) o 'scritta'."""
    propri = {casella.email.lower(), (casella.utente.email or "").lower()} - {""}
    interni = indirizzi_interni() if interni is None else interni
    esterni = {e for e in voce["indirizzi"] if e not in propri and e not in interni}
    contatti = contatti_tra(casella.azienda, esterni)
    if not contatti:
        return "nessuno"
    if EmailSincronizzata.objects.filter(casella=casella, id_esterno=voce["id"]).exists():
        return "gia"
    grezza = fornitore.grezza(voce["id"])
    if not grezza:
        return "nessuno"
    msg = message_from_bytes(grezza, policy=policy.default)
    message_id = str(msg.get("Message-ID") or "").strip()[:255] or f"<{casella.tipo}-{voce['id'][:200]}@posta.adabox>"
    mittente = parseaddr(str(msg.get("From") or ""))[1].lower()
    if mittente in propri:
        autore = casella.utente
    else:
        autore = next((u for u in get_user_model().objects.filter(email__iexact=mittente, is_active=True)[:1]), None) if mittente in interni else None
    record = contatti + [o for o in [opportunita_aperta(contatti)] if o is not None]
    corpo = _corpo(msg, sum(1 for _ in msg.iter_attachments()))
    scritti = []
    for obj in record:
        ct = ct_di(obj)
        if not Messaggio.objects.filter(content_type=ct, object_id=obj.pk, message_id=message_id).exists():
            Messaggio.objects.create(content_type=ct, object_id=obj.pk, tipo=Messaggio.MESSAGGIO, autore=autore,
                                     autore_email="" if autore else mittente[:254], corpo=corpo, message_id=message_id)
        scritti.append([ct.pk, obj.pk])
    try:
        ricevuta = parsedate_to_datetime(str(msg.get("Date"))) if msg.get("Date") else voce.get("quando")
    except (TypeError, ValueError):
        ricevuta = voce.get("quando")
    if ricevuta is not None and timezone.is_naive(ricevuta):
        ricevuta = ricevuta.replace(tzinfo=datetime.timezone.utc)
    EmailSincronizzata.objects.create(casella=casella, id_esterno=voce["id"][:255], message_id=message_id, mittente=mittente[:254],
                                      oggetto=str(msg.get("Subject") or "")[:255], ricevuta_il=ricevuta, record=scritti)
    return "scritta"
