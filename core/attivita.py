"""Attività pianificate su un record qualsiasi (chiamate, email, riunioni, cose da fare)."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import get_connection, send_mail
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from . import chatter
from .generici import ct_di, url_record
from .models import Azienda, AttivitaPianificata, Messaggio


def di(obj):
    return (AttivitaPianificata.objects.filter(content_type=ct_di(obj), object_id=obj.pk)
            .select_related("tipo", "assegnatario"))


def mie(utente):
    return AttivitaPianificata.objects.filter(assegnatario=utente).select_related("tipo", "content_type")


def da_fare_oggi(utente):
    """Quante attività dell'utente sono di oggi o scadute (il numero accanto a "Attività")."""
    return AttivitaPianificata.objects.filter(assegnatario=utente, scadenza__lte=timezone.localdate()).count()


def stato(attivita, oggi=None):
    oggi = oggi or timezone.localdate()
    return "scaduta" if attivita.scadenza < oggi else "oggi" if attivita.scadenza == oggi else "futura"


def pianifica(obj, tipo, assegnatario, scadenza=None, riepilogo="", nota="", creato_da=None):
    azienda = getattr(obj, "azienda", None)
    return AttivitaPianificata.objects.create(
        content_type=ct_di(obj), object_id=obj.pk, tipo=tipo, assegnatario=assegnatario,
        scadenza=scadenza or timezone.localdate() + timedelta(days=tipo.giorni), riepilogo=riepilogo, nota=nota,
        creato_da=creato_da, azienda=azienda if isinstance(azienda, Azienda) else None)


def segna_fatta(attivita, utente, esito=""):
    """Diventa una voce del chatter del record (senza email ai follower) e la riga si cancella."""
    testo = f"{attivita.tipo} fatta" + (f": {attivita.riepilogo}" if attivita.riepilogo else ".")
    if esito.strip():
        testo += f"\n{esito.strip()}"
    if attivita.record is not None:
        chatter.scrivi(attivita.record, utente, testo, tipo=Messaggio.SISTEMA)
    attivita.delete()


def puo_gestire(request, vista, attivita):
    """Segnare fatta o annullare: l'assegnatario, chi l'ha creata o chi può modificare il record."""
    return (request.user.pk in (attivita.assegnatario_id, attivita.creato_da_id)
            or vista.has_change_permission(request, attivita.record))


def raggruppate(utente):
    """Le attività dell'utente divise in scadute, di oggi, prossime, con il link al record."""
    oggi = timezone.localdate()
    gruppi = {"scaduta": [], "oggi": [], "futura": []}
    for a in mie(utente):
        gruppi[stato(a, oggi)].append({"attivita": a, "record": a.record, "url": url_record(a.record) if a.record else None})
    return [("Scadute", "scaduta", gruppi["scaduta"]), ("Oggi", "oggi", gruppi["oggi"]),
            ("Prossime", "futura", gruppi["futura"])]


def promemoria():
    """Lavoro pianificato (ogni mattina): una email per utente con le attività di oggi e scadute."""
    oggi = timezone.localdate()
    utenti = get_user_model().objects.filter(
        Q(attivita_pianificate__scadenza__lte=oggi), is_active=True).exclude(email="").distinct()
    inviate = 0
    with get_connection() as connessione:
        for u in utenti:
            voci = [{"attivita": a, "record": a.record, "url": settings.SITO_URL + (url_record(a.record) or "")}
                    for a in mie(u).filter(scadenza__lte=oggi)]
            testo = render_to_string("core/email/promemoria_attivita.txt", {
                "utente": u, "voci": voci, "oggi": oggi, "link": settings.SITO_URL + "/attivita/"})
            send_mail(f"[{settings.THEME.get('brand', '')}] Attività da fare oggi: {len(voci)}", testo, None, [u.email],
                      connection=connessione)
            inviate += 1
    return inviate
