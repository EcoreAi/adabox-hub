"""La parte del magazzino nel pacchetto per il commercialista: l'inventario valorizzato a fine periodo."""
import calendar
import datetime

from django.utils import timezone

from core.dashboard import queryset
from fatturazione.commercialista import foglio
from fatturazione.scadenzario import numero_csv
from prodotti.models import Prodotto

from . import costi
from .models import Movimento


def fine_periodo(anno, mese):
    giorno = datetime.date(anno, mese or 12, calendar.monthrange(anno, mese or 12)[1])
    return timezone.make_aware(datetime.datetime.combine(giorno, datetime.time.max))


def inventario(request, anno, mese, avvisi):
    if not request.user.has_perm("magazzino.view_movimento") or not queryset(request, Movimento).exists():
        return
    alla = fine_periodo(anno, mese)
    righe = costi.valorizzazione(list(queryset(request, Prodotto).filter(tipo=Prodotto.BENE)), alla)
    if righe:
        yield f"magazzino/inventario-al-{alla:%Y-%m-%d}.csv", foglio(
            ["Codice", "Prodotto", "Metodo", "Quantità", "Costo unitario", "Valore"],
            [[r["prodotto"].codice, r["prodotto"].nome, dict(costi.METODI)[r["metodo"]], numero_csv(r["quantita"]),
              numero_csv(r["costo"]), numero_csv(r["valore"])] for r in righe]
            + [["", "Totale", "", "", "", numero_csv(sum(r["valore"] for r in righe))]])
        if any(r["quantita"] < 0 for r in righe):
            avvisi.append("Inventario: ci sono prodotti con giacenza negativa, da rettificare.")
