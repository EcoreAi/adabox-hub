from django import template

from ai import markdown

register = template.Library()


@register.filter
def markdown_ai(testo):
    return markdown.rendi(testo)


@register.filter
def proposte(messaggio):
    """Le proposte preparate nel turno di una risposta dell'assistente (schede sotto il testo)."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return []
    from ai.models import Proposta
    return Proposta.objects.filter(turno_id=messaggio.turno_id).select_related("azienda")
