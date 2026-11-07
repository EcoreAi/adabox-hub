from django import template

register = template.Library()


@register.simple_tag
def ordini_opportunita(opportunita):
    from vendite.opportunita import ordini_di
    return list(ordini_di(opportunita))


@register.simple_tag
def opportunita_ordine(ordine):
    from vendite.opportunita import di
    return di(ordine)
