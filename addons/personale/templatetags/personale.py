from django import template
from django.utils import timezone

from personale import saldi

register = template.Library()


@register.simple_tag
def saldo_dipendente(dipendente):
    return saldi.saldo(dipendente, timezone.localdate().year)
