import datetime

from django import template

from previsioni import motore
from previsioni.models import PrevisioneArticolo, StatoCalcolo

register = template.Library()


def _fine_orizzonte(riga):
    """L'ultimo giorno coperto dalla previsione: i periodi di `futuro` dal periodo in cui è stata calcolata."""
    from django.utils import timezone
    inizio = motore.inizio(timezone.localtime(riga.calcolata_il).date(), riga.per)
    return motore.avanti(inizio, riga.per, len(riga.futuro)) - datetime.timedelta(days=1)


@register.simple_tag(takes_context=True)
def previsioni_prodotto(context, prodotto):
    """Le previsioni salvate del prodotto per l'azienda corrente, una per magazzino (il totale per ultimo), con
    l'ultimo giorno dell'orizzonte; None se non ce ne sono."""
    azienda = getattr(context.get("request"), "azienda", None)
    if azienda is None:
        return None
    righe = sorted(PrevisioneArticolo.objects.filter(azienda=azienda, prodotto_pk=prodotto.pk),
                   key=lambda r: (r.magazzino_pk is None, r.magazzino))
    if not righe:
        return None
    stato = StatoCalcolo.objects.filter(azienda=azienda, cosa=StatoCalcolo.MAGAZZINO).first()
    ferma_dal = None
    if stato is not None and stato.errore:
        ferma_dal = stato.ultimo_ok or max(r.calcolata_il for r in righe)
    for r in righe:
        r.fine_orizzonte = _fine_orizzonte(r)
        r.motivo = (r.affidabilita.get("motivi") or [""])[0]
    return {"righe": righe, "ferma_dal": ferma_dal}
