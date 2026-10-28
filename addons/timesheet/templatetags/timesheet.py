from django import template
from django.db.models import Sum

from timesheet.models import RigaOre

register = template.Library()


@register.simple_tag
def ore_registrate(**filtro):
    """Somma delle ore registrate per il filtro dato (es. progetto=obj o compito=obj)."""
    return RigaOre.objects.filter(**filtro).aggregate(t=Sum("ore"))["t"] or 0


@register.filter
def percentuale(valore, totale):
    try:
        return min(100, round(100 * float(valore) / float(totale))) if float(totale) else 0
    except (TypeError, ValueError):
        return 0
