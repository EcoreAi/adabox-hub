"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.dashboard import queryset
from core.riepilogo import ATTENZIONE, voce

from .models import Collaudo


def voci(request, dal, oggi):
    miei = queryset(request, Collaudo).filter(stato=Collaudo.APERTO, responsabile=request.user)
    return [voce(ATTENZIONE, miei.count(), "collaudo aperto di cui sei responsabile", "collaudi aperti di cui sei responsabile", reverse("qualita:collaudi_lista"), dettagli=miei)]
