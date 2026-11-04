"""{% agganci "chiave" %}: i template che i moduli hanno agganciato a quel punto con hooks.azione, resi col contesto
corrente. Un modulo spento o un utente senza permesso non vedono niente; un template rotto non rompe la pagina."""
import logging

from django import template
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from core.registry import hooks

register = template.Library()
log = logging.getLogger("core.agganci")


@register.simple_tag(takes_context=True)
def agganci(context, chiave):
    request = context.get("request")
    pezzi = []
    for voce in hooks.azioni_per(chiave, request):
        try:
            pezzi.append(render_to_string(voce["template"], context.flatten(), request=request))
        except Exception:                      # un modulo con un template rotto non deve rompere la pagina altrui
            log.exception("aggancio %s: template %s", chiave, voce["template"])
    return mark_safe("".join(pezzi))
