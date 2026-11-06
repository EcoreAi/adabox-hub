"""Le voci del riepilogo giornaliero: solo ciò che l'utente vede."""
from django.urls import reverse

from core.riepilogo import ATTENZIONE, NOVITA, voce

from . import notifiche
from .models import Notifica


def voci(request, dal, oggi):
    if not request.user.has_perm("discuss.view_canale"):
        return []
    nuove = Notifica.objects.filter(utente=request.user, creata__gte=dal).order_by("-creata")
    return [
        voce(NOVITA, nuove.count(), "nuova notifica: menzione o messaggio diretto", "nuove notifiche: menzioni e messaggi diretti", reverse("discuss:posta"),
             dettagli=[(n.titolo, n.url) for n in nuove[:5]]),
        voce(ATTENZIONE, notifiche.non_lette(request.user), "notifica ancora da leggere", "notifiche ancora da leggere", reverse("discuss:posta")),
    ]
