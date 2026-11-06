"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse
from django.utils import timezone

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, OGGI, dettagli_di, voce
from core.viste.gruppi import numero

from .models import OrdineAcquisto


def _riga(o):
    return f"{o} · {o.fornitore} · {numero(o.totale)} €"


def voci(request, dal, oggi):
    ordini = queryset(request, OrdineAcquisto).select_related("fornitore")
    lista = reverse("acquisti:ordini_lista")
    richieste = ordini.filter(stato=OrdineAcquisto.BOZZA)
    confermati = ordini.filter(stato=OrdineAcquisto.CONFERMATO, confermato_il__gte=timezone.localtime(dal).date())
    attesi = ordini.filter(stato=OrdineAcquisto.CONFERMATO, consegna_prevista=oggi)
    da_approvare = ordini.filter(stato=OrdineAcquisto.DA_APPROVARE)
    return [
        voce(ATTENZIONE, da_approvare.count(), "ordine a fornitore da approvare", "ordini a fornitori da approvare", lista + "?f_stato=da_approvare", dettagli=dettagli_di(da_approvare, _riga)),
        voce(ATTENZIONE, richieste.count(), "richiesta d'acquisto ancora da inviare o confermare", "richieste d'acquisto ancora da inviare o confermare", lista + "?f_stato=bozza", dettagli=dettagli_di(richieste, _riga)),
        voce(NOVITA, confermati.count(), "ordine a fornitore confermato", "ordini a fornitori confermati", lista + "?f_stato=confermato", dettagli=dettagli_di(confermati, _riga)),
        voce(OGGI, attesi.count(), "consegna da fornitore prevista oggi", "consegne da fornitori previste oggi", lista, dettagli=dettagli_di(attesi, _riga)),
    ]
