from django import template

register = template.Library()


@register.simple_tag
def costi_veicolo(veicolo):
    from flotta.models import riepilogo_costi
    return {**riepilogo_costi(veicolo), "scadenze": veicolo.scadenze(30)}
