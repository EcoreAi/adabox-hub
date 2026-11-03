"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from decimal import Decimal

from django.db.models import Sum
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, OGGI, dettagli_di, voce
from core.viste.gruppi import numero

from .models import Fattura, Incasso, Scadenza


def _residuo(scadenze):
    return sum((s.residuo for s in scadenze), Decimal(0))


def _riga(s):
    return f"{s.fattura} · {s.fattura.cliente} · {numero(s.residuo)} € · {s.data:%d/%m/%Y}"


def voci(request, dal, oggi):
    fatture = queryset(request, Fattura).select_related("cliente")
    scadenze = queryset(request, Scadenza).filter(fattura__stato=Fattura.EMESSA, pagata=False).select_related("fattura__cliente").order_by("data")
    incassi = queryset(request, Incasso).filter(tipo=Incasso.INCASSO, creato__gte=dal)
    emesse = fatture.filter(stato=Fattura.EMESSA, emessa_il__gte=dal)
    bozze = fatture.filter(stato=Fattura.BOZZA)
    di_oggi, scadute = list(scadenze.filter(data=oggi)), list(scadenze.filter(data__lt=oggi))
    incassato = incassi.aggregate(t=Sum("importo"))["t"] or 0
    return [
        voce(NOVITA, emesse.count(), "documento emesso", "documenti emessi", reverse("fatturazione:fatture_lista") + "?f_stato=emessa",
             dettagli=dettagli_di(emesse, lambda f: f"{f} · {f.cliente} · {numero(f.totale)} €")),
        voce(NOVITA, incassi.count(), "incasso registrato", "incassi registrati", reverse("fatturazione:incassi_lista"), nota=f"{numero(incassato)} € in tutto"),
        voce(OGGI, len(di_oggi), "pagamento da incassare oggi", "pagamenti da incassare oggi", reverse("fatturazione:scadenze_lista"),
             dettagli=dettagli_di(di_oggi, _riga), nota=f"{numero(_residuo(di_oggi))} €"),
        voce(ATTENZIONE, len(scadute), "pagamento scaduto da incassare", "pagamenti scaduti da incassare", reverse("fatturazione:scadenze_lista"), urgente=True,
             dettagli=dettagli_di(scadute, _riga), nota=f"{numero(_residuo(scadute))} € da incassare"),
        voce(ATTENZIONE, bozze.count(), "fattura in bozza da emettere", "fatture in bozza da emettere", reverse("fatturazione:fatture_lista") + "?f_stato=bozza"),
    ]
