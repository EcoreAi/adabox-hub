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


@register.simple_tag
def provider_accesso():
    """I servizi attivi per entrare senza password (Google, Microsoft), per la pagina di accesso."""
    from portale.accesso_social import attivi
    return attivi()


@register.simple_tag
def indirizzo_ritorno(tipo):
    """L'indirizzo di ritorno da registrare nel servizio: lo stesso che usa l'accesso (SITO_URL)."""
    from django.conf import settings
    from django.urls import reverse
    return settings.SITO_URL + reverse("portale:accedi_ritorno", args=[tipo])
