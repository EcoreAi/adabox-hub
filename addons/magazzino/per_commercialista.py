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



def differenze_inventario(request, anno, mese, avvisi):
    """Le rettifiche degli inventari approvati nel periodo, con il loro valore al costo di magazzino."""
    from .models import Inventario, RigaInventario
    if not request.user.has_perm("magazzino.view_inventario"):
        return
    inventari = queryset(request, Inventario).filter(stato=Inventario.APPROVATO, data__year=anno)
    if mese:
        inventari = inventari.filter(data__month=mese)
    righe = (RigaInventario.objects.filter(inventario__in=inventari, rettifica__isnull=False).exclude(rettifica=0)
             .select_related("inventario", "prodotto", "lotto").order_by("inventario__data", "inventario__pk", "prodotto__nome"))
    if righe:
        yield "magazzino/differenze-inventario.csv", foglio(
            ["Inventario", "Data", "Codice", "Prodotto", "Lotto", "Teorico", "Contato", "Rettifica", "Costo unitario", "Valore"],
            [[r.inventario.numero, r.inventario.data.strftime("%d/%m/%Y"), r.prodotto.codice, r.prodotto.nome, r.lotto.codice if r.lotto else "",
              numero_csv(r.teorico), numero_csv(r.contato), numero_csv(r.rettifica), numero_csv(r.costo_unitario or 0),
              numero_csv(r.valore_rettifica or 0)] for r in righe])
