"""Dati della sezione del webhook: la chiave, l'esempio di verifica e le ultime consegne."""
from django import template

register = template.Library()


@register.simple_tag
def dati_webhook(webhook):
    return {"segreto": webhook.segreto(), "consegne": list(webhook.consegne.all()[:10])}


@register.simple_tag
def dati_collegamento(collegamento):
    from connettori.models import RiferimentoEsterno
    from connettori.sincronia import chiave_azienda
    rif = RiferimentoEsterno.objects.filter(azienda_id=collegamento.azienda_id, sistema=collegamento.sistema)
    aziende = rif.filter(id_esterno__startswith=chiave_azienda("")).count()
    opportunita = rif.filter(content_type__model="opportunita").count()
    return {"collegati": rif.count() - aziende - opportunita, "aziende": aziende, "opportunita": opportunita,
            "record": list(collegamento.record_prova.all()[:30])}
