from django import template
from django.utils import timezone

from capacita import pagine, piano

register = template.Library()


@register.simple_tag
def consegna_progetto(progetto):
    return pagine.scheda_progetto(piano.calcola(progetto.azienda, timezone.localdate()), progetto)
