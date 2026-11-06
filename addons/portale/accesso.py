"""Chi entra nel portale: solo gli utenti esterni con un accesso legato a un contatto. Gli utenti interni hanno le app."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import AccessoPortale


def di(request):
    accesso = AccessoPortale.objects.filter(utente=request.user).select_related("contatto__societa", "contatto__azienda").first()
    if accesso is None:
        raise PermissionDenied("Il portale è riservato ai clienti.")
    return accesso


def portale(vista):
    """Decoratore per le pagine del portale (di qualsiasi app): request.accesso è l'accesso del cliente."""
    @login_required
    def interna(request, *args, **kwargs):
        request.accesso = di(request)
        return vista(request, *args, **kwargs)
    interna.__name__ = vista.__name__
    interna.__doc__ = vista.__doc__
    return interna


def contesto(request, **altro):
    """Il contesto comune ai template del portale (testata, nome del cliente)."""
    return {"accesso": request.accesso, "cliente": request.accesso.cliente, **altro}
