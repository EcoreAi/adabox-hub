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


@register.filter
def artifact(messaggio):
    """Grafici e tabelle prodotti nel turno di una risposta dell'assistente."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return []
    from ai.models import Artifact
    return Artifact.objects.filter(turno_id=messaggio.turno_id)


@register.filter
def svg_artifact(a):
    from django.utils.safestring import mark_safe

    from ai import artifact as modulo
    return mark_safe(modulo.svg_di(a))                  # SVG del kernel: testi già passati da escape


@register.filter
def righe_con_link(dati):
    righe = dati.get("righe", [])
    return zip(righe, list(dati.get("link", [])) + [""] * (len(righe) - len(dati.get("link", []))))
