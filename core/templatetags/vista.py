from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def querystring_con(context, **kwargs):
    """Query string corrente con i parametri dati sostituiti (None li toglie). Inizia con '?'."""
    query = context["request"].GET.copy()
    for chiave, valore in kwargs.items():
        if valore is None:
            query.pop(chiave, None)
        else:
            query[chiave] = valore
    query.pop("partial", None)
    return "?" + query.urlencode() if query else "?"


@register.simple_tag(takes_context=True)
def cella(context, vista, obj, campo):
    return vista.col_valore(context["request"], obj, campo)
