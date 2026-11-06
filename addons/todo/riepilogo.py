"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, OGGI, voce

from .models import Attivita


def voci(request, dal, oggi):
    mie = queryset(request, Attivita).filter(assegnatario=request.user).exclude(stato__in=(Attivita.FATTA, Attivita.ANNULLATA))
    lista = reverse("todo:attivita_lista")
    nuove, di_oggi, scadute = mie.filter(creato__gte=dal).exclude(creato_da=request.user), mie.filter(scadenza=oggi), mie.filter(scadenza__lt=oggi)
    return [
        voce(NOVITA, nuove.count(), "attività nuova assegnata a te", "attività nuove assegnate a te", lista, dettagli=nuove),
        voce(OGGI, di_oggi.count(), "attività in scadenza oggi", "attività in scadenza oggi", lista, dettagli=di_oggi),
        voce(ATTENZIONE, scadute.count(), "attività scaduta", "attività scadute", lista, urgente=True, dettagli=scadute),
    ]
