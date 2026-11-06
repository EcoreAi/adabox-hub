"""Lavori pianificati di AWF (dichiarati nel manifest, eseguiti dal worker)."""
import datetime

from django.utils import timezone

from . import fabbrica, operazioni
from .models import Chiamata, Collegamento

CONSERVA_LETTURE = datetime.timedelta(days=90)


def battito():
    """Ogni 15 minuti: dichiara la versione alla fabbrica, riceve lo stato dell'ingaggio e allinea gli agenti.
    Riallinea anche i permessi degli agenti e toglie dal registro le letture più vecchie di 90 giorni."""
    operazioni.allinea_gruppo()
    Chiamata.objects.filter(effetto="read", creato__lt=timezone.now() - CONSERVA_LETTURE).delete()
    if not Collegamento.attuale().collegato:
        return "non collegato"
    try:
        ingaggio = fabbrica.battito()
    except fabbrica.ErroreFabbrica as e:
        return f"battito non riuscito: {e}"
    return f"ingaggio {ingaggio.get('status') or '?'}, agenti {len(ingaggio.get('agents') or [])}"


def richieste():
    """Ogni 5 minuti: lo stato delle richieste d'ingaggio aperte (§7.3). Una richiesta approvata in Agate porta il
    token della fabbrica: adabox si collega da solo."""
    from .models import RichiestaAgenti
    aperte = RichiestaAgenti.objects.filter(stato__in=RichiestaAgenti.APERTE).count()
    if not aperte:
        return "nessuna richiesta aperta"
    errori = fabbrica.aggiorna_aperte()
    return f"richieste aperte: {aperte}" + (f", errori: {'; '.join(errori)}" if errori else "")
