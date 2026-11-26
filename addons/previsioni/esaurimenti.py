"""Ciò che la lista «Articoli in esaurimento» e il riquadro del prodotto mostrano allo stesso modo."""
import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Max
from django.utils import timezone

from . import motore
from .models import PrevisioneArticolo, PrevisionePronta, StatoCalcolo


def fine_orizzonte(riga):
    """L'ultimo giorno coperto dalla previsione: i periodi di `futuro` dal periodo in cui è stata calcolata."""
    inizio = motore.inizio(timezone.localtime(riga.calcolata_il).date(), riga.per)
    return motore.avanti(inizio, riga.per, len(riga.futuro)) - datetime.timedelta(days=1)


def avviso(azienda, cosa=StatoCalcolo.MAGAZZINO):
    """Se l'ultimo calcolo delle previsioni salvate dell'azienda (di magazzino o di vendite) non è riuscito:
    {"dal": da quando non sono aggiornate (l'ultimo calcolo riuscito, altrimenti la più recente delle righe), o None
    se non ci sono righe («Previsioni non calcolate»), "motivo": il perché, "tentativo": quando si è provato}.
    None se l'ultimo calcolo è riuscito o non c'è stato. Lo mostrano allo stesso modo pagina, lista e riquadro
    (previsioni/_avviso.html)."""
    stato = StatoCalcolo.objects.filter(azienda=azienda, cosa=cosa).first()
    if stato is None or not stato.errore:
        return None
    modello = PrevisioneArticolo if cosa == StatoCalcolo.MAGAZZINO else PrevisionePronta
    ultima = modello.objects.filter(azienda=azienda).aggregate(m=Max("calcolata_il"))["m"]
    return {"dal": (stato.ultimo_ok or ultima) if ultima is not None else None, "motivo": stato.errore,
            "tentativo": stato.ultimo_tentativo}


def quantita(valore):
    """«1.234,5»: una quantità all'italiana, con al più tre decimali e senza zeri in fondo; "" se manca."""
    if valore is None:
        return ""
    testo = f"{Decimal(str(valore)).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP):,.3f}".rstrip("0").rstrip(".")
    return testo.replace(",", "X").replace(".", ",").replace("X", ".")


def fascia_consumo(riga):
    """(basso, alto) del consumo previsto al mese: medie dei quantili 10 % e 90 % di `futuro`, riportate al mese come
    `consumo_mensile` (× 52 / 12 per le serie settimanali)."""
    futuro = riga.futuro or []
    if not futuro:
        return None, None
    fattore = 1 if riga.per == "mese" else 52 / 12
    return (round(sum(f[1] for f in futuro) / len(futuro) * fattore, 3),
            round(sum(f[3] for f in futuro) / len(futuro) * fattore, 3))


def fascia(riga):
    """«08/03/2027 – 18/04/2027»; un estremo oltre l'orizzonte è «oltre …». Vuoto senza il primo estremo."""
    if not riga.esaurimento_da:
        return ""
    fine = riga.esaurimento_a
    a = fine.strftime("%d/%m/%Y") if fine else f"oltre {fine_orizzonte(riga):%d/%m/%Y}"
    return f"{riga.esaurimento_da:%d/%m/%Y} – {a}"
