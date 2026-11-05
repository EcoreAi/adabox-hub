"""Dati della sezione del webhook: la chiave, l'esempio di verifica e le ultime consegne."""
from django import template

register = template.Library()


@register.simple_tag
def dati_webhook(webhook):
    return {"segreto": webhook.segreto(), "consegne": list(webhook.consegne.all()[:10])}


@register.simple_tag
def dati_collegamento(collegamento):
    from connettori.models import RiferimentoEsterno
    return {"collegati": RiferimentoEsterno.objects.filter(azienda_id=collegamento.azienda_id, sistema=collegamento.sistema).count(),
            "record": list(collegamento.record_prova.all()[:20])}
