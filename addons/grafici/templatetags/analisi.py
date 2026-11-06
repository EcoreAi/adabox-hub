from django import template

from .. import motore

register = template.Library()


@register.simple_tag(takes_context=True)
def schede_analisi(context, attiva=""):
    """Le schede della dashboard per chi guarda (pagine proprie, condivise, app con indicatori)."""
    request = context.get("request")
    if request is None or not request.user.is_authenticated:
        return []
    return motore.schede(request, attiva or "")


@register.simple_tag(takes_context=True)
def destinazioni_analisi(context, vista=""):
    """[(valore, etichetta)] delle pagine in cui salvare un grafico."""
    return motore.destinazioni(context["request"], vista or "")


@register.filter
def euro_o_numero(valore):
    from core.viste.gruppi import numero
    return numero(valore)
