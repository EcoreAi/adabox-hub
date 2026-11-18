"""Moduli inviati con un token CSRF vecchio: una pagina rimasta aperta, o l'app ripresa sul telefono dopo un accesso
fatto altrove (il token cambia a ogni accesso). Sul login non serve un 403: si ricarica la pagina con un token nuovo."""
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.views.csrf import csrf_failure

AVVISO_LOGIN = "La pagina di accesso era rimasta aperta troppo a lungo: inserisci di nuovo le credenziali."


def errore_csrf(request, reason=""):
    if request.method == "POST" and request.path == reverse("login"):
        messages.warning(request, AVVISO_LOGIN)
        return redirect(request.get_full_path())
    return csrf_failure(request, reason=reason)
