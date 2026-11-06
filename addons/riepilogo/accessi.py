"""A ogni accesso: l'accesso precedente diventa il punto di partenza del riepilogo, e la scheda si apre da sola se l'utente lo vuole."""
from django.utils import timezone

from core.middleware import esterno

from .models import Preferenza

CHIAVE_SESSIONE = "riepilogo_apri"


def di(utente):
    return Preferenza.objects.get_or_create(utente=utente)[0]


def registra(sender, request, user, **kwargs):
    if esterno(user):
        return
    p = di(user)
    p.accesso_precedente, p.ultimo_accesso = p.ultimo_accesso, timezone.now()
    p.save(update_fields=["accesso_precedente", "ultimo_accesso"])
    if request is None or not hasattr(request, "session"):
        return
    if p.mostra_al_login:
        request.session[CHIAVE_SESSIONE] = True
    else:
        request.session.pop(CHIAVE_SESSIONE, None)       # un residuo di una sessione vecchia non deve aprirla lo stesso
