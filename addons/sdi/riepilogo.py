"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
import datetime

from django.db.models import Sum
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, dettagli_di, voce
from core.viste.gruppi import numero

from .models import FatturaPassiva, ScadenzaPassiva


def _somma(qs):
    return numero(qs.aggregate(t=Sum("importo"))["t"] or 0)


def voci(request, dal, oggi):
    passive = queryset(request, FatturaPassiva).select_related("fornitore")
    pagamenti = queryset(request, ScadenzaPassiva).filter(pagata=False).select_related("fattura__fornitore").order_by("data")
    ricevute, da_verificare = passive.filter(ricevuta_il__gte=dal), passive.filter(stato=FatturaPassiva.DA_VERIFICARE)
    scadute = pagamenti.filter(data__lt=oggi)
    vicine = pagamenti.filter(data__gte=oggi, data__lte=oggi + datetime.timedelta(days=7))
    riga = lambda s: f"{s.fattura.fornitore} · {s.fattura.numero} · {numero(s.residuo)} € · {s.data:%d/%m/%Y}"      # noqa: E731
    return [
        voce(NOVITA, ricevute.count(), "fattura ricevuta da un fornitore", "fatture ricevute dai fornitori", reverse("sdi:passive_lista"),
             dettagli=dettagli_di(ricevute, lambda f: f"{f.fornitore} · {f.numero} · {numero(f.totale)} €")),
        voce(ATTENZIONE, da_verificare.count(), "fattura di fornitore da verificare", "fatture di fornitori da verificare", reverse("sdi:passive_lista") + "?f_stato=da_verificare"),
        voce(ATTENZIONE, scadute.count(), "pagamento a fornitore scaduto", "pagamenti a fornitori scaduti", reverse("sdi:pagamenti_lista"), urgente=True,
             dettagli=dettagli_di(scadute, riga), nota=f"{_somma(scadute)} €"),
        voce(ATTENZIONE, vicine.count(), "pagamento a fornitore entro 7 giorni", "pagamenti a fornitori entro 7 giorni", reverse("sdi:pagamenti_lista"),
             dettagli=dettagli_di(vicine, riga), nota=f"{_somma(vicine)} €"),
    ]
