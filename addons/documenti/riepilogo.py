"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, OGGI, voce

from .models import Richiesta


def voci(request, dal, oggi):
    mie = queryset(request, Richiesta).filter(destinatario=request.user, stato=Richiesta.APERTA)
    lista = reverse("documenti:richieste_lista")
    nuove, di_oggi, scadute = mie.filter(creata__gte=dal), mie.filter(scadenza=oggi), mie.filter(scadenza__lt=oggi)
    return [
        voce(NOVITA, nuove.count(), "documento nuovo richiesto a te", "documenti nuovi richiesti a te", lista, dettagli=nuove),
        voce(OGGI, di_oggi.count(), "documento da consegnare oggi", "documenti da consegnare oggi", lista, dettagli=di_oggi),
        voce(ATTENZIONE, scadute.count(), "documento richiesto in ritardo", "documenti richiesti in ritardo", lista, urgente=True, dettagli=scadute),
    ]
