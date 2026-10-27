"""Lavori pianificati di To-Do (dichiarati nel manifest, eseguiti dal worker)."""
import datetime

from django.conf import settings
from django.core.mail import get_connection, send_mail
from django.utils import timezone

from core import parametri
from core.generici import url_record
from core.models import Azienda

from .models import Attivita


def promemoria_scadenze():
    """Ogni mattina: a ogni assegnatario le sue attività aperte in scadenza entro i giorni di preavviso
    dell'azienda (parametro todo.giorni_preavviso). Restituisce il numero di email inviate."""
    oggi = timezone.localdate()
    per_utente = {}
    for azienda in Azienda.objects.filter(attiva=True):
        limite = oggi + datetime.timedelta(days=parametri.leggi("todo.giorni_preavviso", azienda))
        for a in (Attivita.objects.filter(azienda=azienda, scadenza__lte=limite,
                                          stato__in=[Attivita.APERTA, Attivita.IN_CORSO])
                  .exclude(assegnatario=None).exclude(assegnatario__email="").select_related("assegnatario")):
            per_utente.setdefault(a.assegnatario, []).append(a)
    brand = settings.THEME.get("brand", "")
    with get_connection() as connessione:
        for utente, voci in per_utente.items():
            righe = [f"- {a.scadenza:%d/%m/%Y} {a.numero} {a.titolo}\n  {settings.SITO_URL}{url_record(a) or ''}"
                     for a in sorted(voci, key=lambda a: a.scadenza)]
            send_mail(f"[{brand}] Attività in scadenza: {len(voci)}",
                      "Attività in scadenza o scadute:\n\n" + "\n".join(righe) + "\n", None, [utente.email],
                      connection=connessione)
    return len(per_utente)
