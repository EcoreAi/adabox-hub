"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, voce

from .models import Consegna, Ricevimento


def voci(request, dal, oggi):
    consegne = queryset(request, Consegna).filter(stato=Consegna.BOZZA)
    ricevimenti = queryset(request, Ricevimento).filter(stato=Ricevimento.BOZZA)
    return [
        voce(ATTENZIONE, consegne.count(), "consegna da spedire", "consegne da spedire", reverse("magazzino:consegne_lista"), dettagli=consegne),
        voce(ATTENZIONE, ricevimenti.count(), "ricevimento atteso da un fornitore", "ricevimenti attesi dai fornitori", reverse("magazzino:ricevimenti_lista"), dettagli=ricevimenti),
    ]
