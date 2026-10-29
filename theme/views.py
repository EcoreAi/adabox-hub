from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import cache_control


@cache_control(max_age=86400)
def favicon(request):
    """Lo stesso cubo del logo nell'header."""
    svg = render_to_string("theme/partials/_logo.html").strip()          # il commento del template non esce
    svg = svg.replace('<svg class="ui-logo-cubo"', '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return HttpResponse(svg, content_type="image/svg+xml")
