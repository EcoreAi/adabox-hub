from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def sezioni_portale(context):
    """Le sezioni del portale per la testata (senza riepilogo)."""
    from portale import sezioni
    request = context.get("request")
    return sezioni.per(getattr(request, "accesso", None))


@register.simple_tag
def accesso_del_contatto(contatto):
    from portale.models import AccessoPortale
    return AccessoPortale.objects.filter(contatto=contatto).select_related("utente").first()
