from django import template
from django.db.models import Sum

from timesheet.models import Cronometro, RigaOre

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


@register.simple_tag(takes_context=True)
def cronometro_attivo(context):
    utente = context["request"].user
    return Cronometro.objects.filter(utente=utente).select_related("compito", "progetto").first() if utente.is_authenticated else None
