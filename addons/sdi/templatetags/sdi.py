from django import template

from sdi import servizi

register = template.Library()


@register.simple_tag
def stato_sdi(fattura):
    return {"trasmissioni": list(fattura.trasmissioni.prefetch_related("notifiche")),
            "puo_inviare": servizi.puo_inviare(fattura)}
