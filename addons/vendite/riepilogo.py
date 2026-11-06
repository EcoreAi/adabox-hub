"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
import datetime

from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, dettagli_di, voce
from core.viste.gruppi import numero

from .models import OrdineVendita


def _riga(o):
    return f"{o} · {o.cliente} · {numero(o.totale)} €"


def voci(request, dal, oggi):
    ordini = queryset(request, OrdineVendita).select_related("cliente")
    lista = reverse("vendite:ordini_lista")
    confermati = ordini.filter(stato=OrdineVendita.CONFERMATO, confermato_il__gte=timezone.localtime(dal).date())
    accettati = ordini.filter(risposta=OrdineVendita.ACCETTATO, risposta_il__gte=dal)
    rifiutati = ordini.filter(risposta=OrdineVendita.RIFIUTATO, risposta_il__gte=dal)
    inviati = ordini.filter(stato=OrdineVendita.INVIATO)
    in_scadenza = inviati.filter(validita__gte=oggi, validita__lte=oggi + datetime.timedelta(days=7))
    scaduti = inviati.filter(validita__lt=oggi)
    totale = confermati.aggregate(t=Sum("totale"))["t"] or 0
    return [
        voce(NOVITA, confermati.count(), "ordine confermato", "ordini confermati", lista + "?f_stato=confermato", dettagli=dettagli_di(confermati, _riga),
             nota=f"{numero(totale)} € in tutto" if confermati.count() > 1 else ""),
        voce(NOVITA, accettati.count(), "preventivo accettato online dal cliente", "preventivi accettati online dai clienti", lista, dettagli=dettagli_di(accettati, _riga)),
        voce(NOVITA, rifiutati.count(), "preventivo rifiutato online dal cliente", "preventivi rifiutati online dai clienti", lista, dettagli=dettagli_di(rifiutati, _riga)),
        voce(ATTENZIONE, in_scadenza.count(), "preventivo scade entro 7 giorni", "preventivi scadono entro 7 giorni", lista + "?f_stato=inviato", dettagli=dettagli_di(in_scadenza, _riga)),
        voce(ATTENZIONE, scaduti.count(), "preventivo scaduto senza risposta", "preventivi scaduti senza risposta", lista + "?f_stato=inviato", urgente=True, dettagli=dettagli_di(scaduti, _riga)),
    ]
