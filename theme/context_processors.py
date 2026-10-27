from django.conf import settings

DEFAULTS = {
    "brand": "Progetto",
    "mark": "PR",
    "company": "",
    "company_url": "",
    "version": "",
    "nav": [],
}


def theme(request):
    """Espone `theme` ai template: default + settings.THEME."""
    return {"theme": {**DEFAULTS, **getattr(settings, "THEME", {})}}
