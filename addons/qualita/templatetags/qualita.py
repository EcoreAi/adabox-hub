from django import template

from ..models import Collaudo, Esecuzione

register = template.Library()


@register.simple_tag
def collaudi_del_rilascio(rilascio):
    return list(Collaudo.objects.filter(rilascio=rilascio).select_related("ambiente"))


@register.simple_tag
def esecuzioni_del_difetto(compito):
    return list(Esecuzione.objects.filter(difetto=compito).select_related("collaudo", "caso"))


@register.filter
def pill_esito(esito):
    return {"superato": "ui-pill-ok", "fallito": "ui-pill-danger", "bloccato": "ui-pill-warn",
            "in corso": "ui-pill-info"}.get(esito, "ui-pill-neutral")
