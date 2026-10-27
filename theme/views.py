from django.conf import settings
from django.http import HttpResponse
from django.utils.html import escape
from django.views.decorators.cache import cache_control

from .context_processors import DEFAULTS

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="{bg}"/>'
    '<text x="32" y="41" text-anchor="middle" font-family="-apple-system,Segoe UI,Roboto,Arial,sans-serif" '
    'font-size="{size}" font-weight="700" fill="#fff">{mark}</text></svg>'
)


@cache_control(max_age=86400)
def favicon(request):
    """Badge quadrato con la sigla del brand, stesso look del badge nell'header."""
    mark = {**DEFAULTS, **getattr(settings, "THEME", {})}["mark"][:3]
    size = {1: 36, 2: 28, 3: 22}[max(1, len(mark))]
    svg = SVG.format(bg="#1e3a8a", size=size, mark=escape(mark))
    return HttpResponse(svg, content_type="image/svg+xml")
