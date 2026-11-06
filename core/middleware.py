from .azienda import corrente


def esterno(user):
    """Un utente esterno (es. il cliente di un portale): vede solo gli indirizzi del portale."""
    if not getattr(user, "is_authenticated", False) or user.is_superuser:
        return False
    try:
        return user.profilo.esterno
    except Exception:                                   # senza profilo: utente interno
        return False


class UtenteEsternoMiddleware:
    """Gli utenti esterni restano nel portale: ogni altro indirizzo (pagine interne, API, admin) rimanda alla home
    del portale. Sempre ammessi: accesso, uscita, password, file statici, favicon."""
    SEMPRE = ("/accounts/", "/static/", "/favicon.")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.shortcuts import redirect, render
        if esterno(getattr(request, "user", None)):
            from .registry import hooks
            percorso = request.path_info
            ammessi = (*self.SEMPRE, *settings.PORTALE_PERCORSI, *hooks.percorsi_portale())
            if not percorso.startswith(ammessi):
                if settings.PORTALE_HOME and percorso != settings.PORTALE_HOME:
                    return redirect(settings.PORTALE_HOME)
                return render(request, "core/solo_portale.html", status=403)
        return self.get_response(request)


class DueFattoriObbligoMiddleware:
    """Con la 2FA obbligatoria, chi non l'ha ancora attivata resta sulla pagina di attivazione. Le API con il token
    restano fuori: non hanno una pagina da mostrare."""
    SEMPRE = ("/accounts/", "/static/", "/favicon.", "/profilo/due-fattori/", "/api/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not esterno(user) \
                and not request.path_info.startswith(self.SEMPRE):
            from django.shortcuts import redirect

            from . import due_fattori
            if due_fattori.obbligatoria_per(user) and not due_fattori.attiva(user):
                return redirect("core:due_fattori")
        return self.get_response(request)


class ModuloDisattivatoMiddleware:
    """Le pagine e le API di un modulo disattivato rispondono 404 con un avviso, per tutti: il modulo resta
    installato con i suoi dati e si riaccende dalla pagina Moduli."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.shortcuts import render

        from .registry.modules import disattivati
        modulo = modulo_di(request.path_info)
        # il database si interroga solo per gli indirizzi di un modulo (non per kernel, login, file statici)
        if modulo in settings.ADDONS_ATTIVI and modulo in disattivati():
            return render(request, "core/modulo_disattivato.html", status=404)
        return self.get_response(request)


class LicenzaScadutaMiddleware:
    """Licenza assente, non valida o scaduta oltre la grazia: i dati si leggono ma non si scrivono. Restano aperti
    l'accesso e le pagine da cui si rimette a posto la licenza."""
    SEMPRE = ("/accounts/", "/static/", "/favicon.", "/moduli/", "/applicazioni/")
    LETTURA = ("GET", "HEAD", "OPTIONS")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in self.LETTURA and not request.path_info.startswith(self.SEMPRE):
            from django.shortcuts import render

            from . import licenza
            if licenza.bloccata():
                return render(request, "core/licenza_scaduta.html", status=403)
        return self.get_response(request)


def modulo_di(percorso):
    """Il modulo di un indirizzo: il namespace delle sue pagine, o /api/v1/<modulo>/ per le API."""
    from django.urls import Resolver404, resolve
    parti = percorso.strip("/").split("/")
    if len(parti) >= 3 and parti[0] == "api":
        return parti[2]
    try:
        return resolve(percorso).namespace.split(":")[0]
    except Resolver404:
        return None


class AziendaCorrenteMiddleware:
    """request.azienda: l'azienda corrente, o None per l'anonimo e per chi non ne ha una attiva.

    Si risolve subito e non in modo lazy: un oggetto lazy che avvolge None non è None, quindi i controlli
    `azienda is None` non scattavano e i filtri `azienda=request.azienda` finivano in un errore 500."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        request.azienda = corrente(request) if user is not None and user.is_authenticated else None
        return self.get_response(request)
