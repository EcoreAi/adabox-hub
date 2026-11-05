"""Dati della sezione del webhook: la chiave, l'esempio di verifica e le ultime consegne."""
from django import template

register = template.Library()


@register.simple_tag
def dati_webhook(webhook):
    return {"segreto": webhook.segreto(), "consegne": list(webhook.consegne.all()[:10])}
