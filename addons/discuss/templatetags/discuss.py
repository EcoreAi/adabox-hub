from django import template

from core import allegati
from discuss import testo

register = template.Library()


@register.filter
def messaggio_html(corpo):
    return testo.rendi(corpo)


@register.filter
def testo_piano(corpo):
    return testo.piano(corpo)


@register.filter
def evidenzia(corpo, q):
    return testo.evidenzia(corpo, q)


@register.filter
def allegati_messaggio(messaggio):
    return allegati.di(messaggio)


@register.filter
def iniziale(utente):
    return ((utente.get_full_name() or utente.username)[:1] if utente else "?").upper()


@register.filter
def titolo_canale(canale, utente):
    return canale.titolo_per(utente)


@register.simple_tag
def notifiche_non_lette(utente):
    from discuss import notifiche
    return notifiche.non_lette(utente) if utente.is_authenticated else 0


@register.simple_tag(takes_context=True)
def lega_record_creato(context):
    """Sul dettaglio di un record: se è nato da un messaggio, lo lega alla conversazione."""
    from discuss import schede
    request, obj = context.get("request"), context.get("obj")
    if request is not None and obj is not None:
        schede.lega_creato(request, obj)
    return ""


@register.simple_tag
def guida_connessione(connessione, request):
    from discuss import connettori
    url = connettori.url_webhook(connessione)
    return {"webhook": url, "https": url.startswith("https://")}


@register.simple_tag
def conoscenza_sportello(sportello):
    from discuss import ia
    return {"n_voci": sportello.conoscenza.filter(attiva=True).count(), "ai_attiva": ia.disponibile(),
            "senza_risposta": list(sportello.senza_risposta.filter(risolta=False)[:30])}


@register.filter
def ct_id(obj):
    from core.generici import ct_di
    return ct_di(obj).pk


@register.simple_tag
def squilli_per(utente):
    """Le chiamate che stanno squillando per questa persona, su qualsiasi pagina."""
    from discuss import chiamate
    return chiamate.squilli_per(utente) if utente.is_authenticated else []


@register.simple_tag
def sportelli_pubblici(obj):
    """Gli sportelli il cui assistente riferisce ai visitatori questa pagina o questo spazio della wiki."""
    from discuss import conoscenza_wiki
    spazio_id = getattr(obj, "spazio_id", None) or obj.pk
    return conoscenza_wiki.sportelli_che_la_dicono(spazio_id)
