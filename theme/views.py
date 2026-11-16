from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import cache_control


def colore_tema():
    from django.conf import settings

    from .context_processors import DEFAULTS, tema_corrente
    tema = tema_corrente()
    return (tema and tema.colore_barra) or {**DEFAULTS, **getattr(settings, "THEME", {})}["theme_color"]


@cache_control(max_age=86400)
def favicon(request):
    """theme/partials/_favicon.svg: di default lo stesso cubo del logo nell'header; un tema lo sostituisce."""
    svg = render_to_string("theme/partials/_favicon.svg").strip()        # il commento del template non esce
    svg = svg.replace('<svg class="ui-logo-cubo"', '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return HttpResponse(svg, content_type="image/svg+xml")


def _icona_png(lato):
    """Le icone dell'app installata: theme/icona-<lato>.png tra gli statici se un tema la fornisce (un'app che
    viene prima di theme in INSTALLED_APPS), altrimenti il cubo del logo su fondo bianco, disegnato con Pillow."""
    from django.contrib.staticfiles import finders
    trovata = finders.find(f"theme/icona-{lato}.png")
    if trovata:
        with open(trovata, "rb") as f:
            return f.read()
    from io import BytesIO

    from PIL import Image, ImageDraw
    scala = lato / 32 * 0.62                     # margine ampio: va bene anche come icona «maskable»
    spost = (lato - 32 * scala) / 2
    img = Image.new("RGB", (lato, lato), "#ffffff")
    d = ImageDraw.Draw(img)

    def p(*punti):
        return [(spost + x * scala, spost + y * scala) for x, y in punti]
    d.polygon(p((16, 4.5), (26, 10.25), (16, 16), (6, 10.25)), fill="#5b7be0")
    d.polygon(p((6, 10.25), (16, 16), (16, 27.5), (6, 21.75)), fill="#2945a3")
    d.polygon(p((26, 10.25), (16, 16), (16, 27.5), (26, 21.75)), fill="#1e3a8a")
    uscita = BytesIO()
    img.save(uscita, "PNG")
    return uscita.getvalue()


@cache_control(max_age=86400)
def icona(request, lato):
    if lato not in (180, 192, 512):
        from django.http import Http404
        raise Http404
    return HttpResponse(_icona_png(lato), content_type="image/png")


@cache_control(max_age=3600)
def manifest(request):
    import json

    from django.conf import settings
    from django.urls import reverse
    brand = settings.THEME.get("brand", "adabox")
    dati = {"name": brand, "short_name": brand[:12], "lang": "it", "dir": "ltr",
            "start_url": "/tasca/?da=app", "scope": "/", "display": "standalone", "background_color": "#ffffff", "theme_color": colore_tema(),
            "description": "Il gestionale con l'assistente: attività, approvazioni, note spese e notifiche anche dal telefono.",
            "icons": [{"src": reverse("theme:icona", args=[192]), "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
                      {"src": reverse("theme:icona", args=[512]), "sizes": "512x512", "type": "image/png", "purpose": "any maskable"}],
            "shortcuts": [{"name": "Da approvare", "url": "/approvazioni/"}, {"name": "Le mie attività", "url": "/attivita/"}]}
    return HttpResponse(json.dumps(dati, ensure_ascii=False), content_type="application/manifest+json")


def service_worker(request):
    from django.template.loader import render_to_string
    risposta = HttpResponse(render_to_string("theme/sw.js"), content_type="application/javascript")
    risposta["Service-Worker-Allowed"] = "/"
    risposta["Cache-Control"] = "no-cache"
    return risposta


def offline(request):
    from django.shortcuts import render
    return render(request, "theme/offline.html")


@cache_control(max_age=31536000, public=True)                     # l'URL cambia con ?v= a ogni modifica
def tema_css(request, pk):
    from django.shortcuts import get_object_or_404

    from .models import Tema
    tema = get_object_or_404(Tema.objects.only("css"), pk=pk)
    risposta = HttpResponse(tema.css, content_type="text/css; charset=utf-8")
    risposta["X-Content-Type-Options"] = "nosniff"
    return risposta


@cache_control(max_age=31536000, public=True)
def tema_logo(request, pk):
    from django.http import Http404
    from django.shortcuts import get_object_or_404

    from .models import LOGO_TIPI, Tema
    tema = get_object_or_404(Tema.objects.only("logo", "logo_tipo"), pk=pk)
    if not tema.logo or tema.logo_tipo not in LOGO_TIPI:
        raise Http404
    risposta = HttpResponse(bytes(tema.logo), content_type=tema.logo_tipo)
    risposta["X-Content-Type-Options"] = "nosniff"
    if tema.logo_tipo == "image/svg+xml":                           # aperto da solo: niente script né risorse esterne
        risposta["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return risposta


def _solo_staff(vista):
    from functools import wraps

    from django.contrib.admin.views.decorators import staff_member_required
    return staff_member_required(wraps(vista)(vista))


@_solo_staff
def anteprima(request, pk):
    """Il tema si vede solo in questa sessione, finché non la chiudi: gli altri continuano con quello attivo."""
    from django.shortcuts import get_object_or_404, redirect

    from .context_processors import SESSIONE_ANTEPRIMA
    from .models import Tema
    request.session[SESSIONE_ANTEPRIMA] = get_object_or_404(Tema, pk=pk).pk
    return redirect("/")


@_solo_staff
def anteprima_fine(request):
    from django.shortcuts import redirect
    from django.utils.http import url_has_allowed_host_and_scheme

    from .context_processors import SESSIONE_ANTEPRIMA
    request.session.pop(SESSIONE_ANTEPRIMA, None)
    dopo = request.GET.get("next", "")
    sicuro = url_has_allowed_host_and_scheme(dopo, {request.get_host()}, require_https=request.is_secure())
    return redirect(dopo if dopo and sicuro else "admin:theme_tema_changelist")
