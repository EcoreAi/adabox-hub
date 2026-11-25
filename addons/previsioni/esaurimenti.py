"""Ciò che la lista «Articoli in esaurimento» e il riquadro del prodotto mostrano allo stesso modo."""
import datetime

from django.utils import timezone

from . import motore
from .models import StatoCalcolo


def fine_orizzonte(riga):
    """L'ultimo giorno coperto dalla previsione: i periodi di `futuro` dal periodo in cui è stata calcolata."""
    inizio = motore.inizio(timezone.localtime(riga.calcolata_il).date(), riga.per)
    return motore.avanti(inizio, riga.per, len(riga.futuro)) - datetime.timedelta(days=1)


def non_aggiornata_dal(azienda, righe):
    """Da quando le previsioni di magazzino non sono aggiornate (l'ultimo calcolo è fallito), altrimenti None."""
    stato = StatoCalcolo.objects.filter(azienda=azienda, cosa=StatoCalcolo.MAGAZZINO).first()
    if stato is None or not stato.errore:
        return None
    if stato.ultimo_ok:
        return stato.ultimo_ok
    return max((r.calcolata_il for r in righe), default=None)


def fascia(riga):
    """«08/03/2027 – 18/04/2027»; un estremo oltre l'orizzonte è «oltre …». Vuoto senza il primo estremo."""
    if not riga.esaurimento_da:
        return ""
    fine = riga.esaurimento_a
    a = fine.strftime("%d/%m/%Y") if fine else f"oltre {fine_orizzonte(riga):%d/%m/%Y}"
    return f"{riga.esaurimento_da:%d/%m/%Y} – {a}"
