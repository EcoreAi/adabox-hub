"""Decoratori delle viste del kernel e dei moduli.

`post_con_accesso` sostituisce la coppia `@require_POST` + `@login_required` nelle azioni che rispondono solo a un POST
(cambio azienda, allegati, chatter, token…). Con `login_required` un POST a sessione scaduta andava al login con
`next=<l'azione>`, e dopo l'accesso quell'indirizzo, aperto con un GET, rispondeva 405 senza via d'uscita. Qui chi non è
collegato torna alla pagina da cui veniva."""
from functools import wraps
from urllib.parse import unquote, urlsplit

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse
from django.urls import Resolver404, resolve
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST


def e_solo_post(url):
    """True se l'indirizzo (percorso, con o senza query) risolve a una vista segnata «solo POST»."""
    percorso = unquote(urlsplit(url or "").path) or "/"
    for prova in (percorso, percorso + "/"):       # APPEND_SLASH porterebbe da «/x» a «/x/»
        try:
            vista = resolve(prova).func
        except Resolver404:
            continue
        return bool(getattr(vista, "solo_post", False))
    return False


def _sicuro(request, url):
    return bool(url) and url_has_allowed_host_and_scheme(
        url, allowed_hosts={request.get_host()}, require_https=request.is_secure()) and not e_solo_post(url)


def pagina_di_ritorno(request):
    """Dove mandare chi deve accedere di nuovo: il campo `next` del form, il Referer dello stesso sito, altrimenti `/`."""
    candidato = request.POST.get("next", "")
    if _sicuro(request, candidato):
        return candidato
    parti = urlsplit(request.headers.get("Referer", ""))
    if parti.netloc == request.get_host() and parti.scheme in ("http", "https"):
        candidato = parti.path + ("?" + parti.query if parti.query else "")
        if _sicuro(request, candidato):
            return candidato
    return "/"


def post_con_accesso(vista):
    """Azione solo POST per chi è collegato. Non collegato: al login con `next` = la pagina di partenza (con HTMX,
    204 e `HX-Redirect`, perché sia la pagina intera ad andare al login). Collegato con un altro metodo: 405."""
    solo_post = require_POST(vista)

    @wraps(vista)
    def avvolta(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login = redirect_to_login(pagina_di_ritorno(request))
            if request.headers.get("HX-Request"):
                risposta = HttpResponse(status=204)
                risposta["HX-Redirect"] = login["Location"]
                return risposta
            return login
        return solo_post(request, *args, **kwargs)

    avvolta.solo_post = True
    return avvolta
