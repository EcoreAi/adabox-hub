"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.riepilogo import ATTENZIONE, voce

from . import decisioni


def voci(request, dal, oggi):
    return [voce(ATTENZIONE, decisioni.conteggio(request.user), "decisione dell'AI aspetta la tua approvazione", "decisioni dell'AI aspettano la tua approvazione", reverse("agate:da_approvare"))]
