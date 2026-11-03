"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, NOVITA, OGGI, voce

from .models import Compito, Milestone


def voci(request, dal, oggi):
    compiti = queryset(request, Compito).filter(assegnatari=request.user, fase__chiusa=False).distinct()
    lista = reverse("progetti:compiti_kanban")
    nuovi, di_oggi, scaduti = compiti.filter(creato__gte=dal), compiti.filter(scadenza=oggi), compiti.filter(scadenza__lt=oggi)
    milestone = queryset(request, Milestone).filter(scadenza=oggi)
    return [
        voce(NOVITA, nuovi.count(), "compito nuovo assegnato a te", "compiti nuovi assegnati a te", lista, dettagli=nuovi),
        voce(OGGI, di_oggi.count(), "compito in scadenza oggi", "compiti in scadenza oggi", lista, dettagli=di_oggi),
        voce(OGGI, milestone.count(), "milestone in scadenza oggi", "milestone in scadenza oggi", reverse("progetti:milestone_lista"), dettagli=milestone),
        voce(ATTENZIONE, scaduti.count(), "compito scaduto", "compiti scaduti", lista, urgente=True, dettagli=scaduti),
    ]
