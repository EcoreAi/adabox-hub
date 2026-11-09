from django.conf import settings

DEFAULTS = {
    "brand": "Progetto",
    "mark": "PR",
    "company": "",
    "company_url": "",
    "version": "",
    "nav": [],
    "theme_color": "#1e3a8a",   # barra del browser sul telefono e manifest dell'app installata
}


def theme(request):
    """Espone `theme` ai template: default + settings.THEME."""
    return {"theme": {**DEFAULTS, **getattr(settings, "THEME", {})}}
