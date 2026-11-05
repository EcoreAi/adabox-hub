from django import template

from ai import markdown

register = template.Library()


@register.filter
def markdown_ai(testo):
    return markdown.rendi(testo)


@register.filter
def proposte(messaggio):
    """Le proposte preparate nel turno di una risposta dell'assistente (schede sotto il testo)."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return []
    from ai.models import Proposta
    return Proposta.objects.filter(turno_id=messaggio.turno_id).select_related("azienda")


@register.filter
def artifact(messaggio):
    """Grafici e tabelle prodotti nel turno di una risposta dell'assistente."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return []
    from ai.models import Artifact
    return Artifact.objects.filter(turno_id=messaggio.turno_id)


@register.filter
def documenti(messaggio):
    """I documenti scritti o modificati da Ada nel turno di una risposta."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return []
    from ai.models import DocumentoChat
    return DocumentoChat.objects.filter(versioni__turno_id=messaggio.turno_id).distinct()


@register.filter
def svg_artifact(a):
    from django.utils.safestring import mark_safe

    from ai import artifact as modulo
    return mark_safe(modulo.svg_di(a))                  # SVG del kernel: testi già passati da escape


@register.filter
def righe_con_link(dati):
    righe = dati.get("righe", [])
    return zip(righe, list(dati.get("link", [])) + [""] * (len(righe) - len(dati.get("link", []))))



@register.filter
def provenienza(messaggio):
    """La provenienza calcolata a fine turno di una risposta dell'assistente ({} se non c'è)."""
    if getattr(messaggio, "ruolo", "") != "assistente" or not messaggio.turno_id:
        return {}
    turno = messaggio.turno
    return {**(turno.provenienza or {}), "modello": turno.modello, "costo": turno.costo} if turno.provenienza else {}


@register.filter
def allegati(messaggio):
    """I file allegati a un messaggio dell'utente."""
    from ai import allegati_chat
    return allegati_chat.di(messaggio) if getattr(messaggio, "ruolo", "") == "utente" else []


@register.filter
def voto(messaggio):
    """Il voto dato a una risposta dell'assistente, se c'è."""
    from ai.models import ValutazioneRisposta
    return ValutazioneRisposta.objects.filter(messaggio=messaggio).first()


@register.simple_tag
def ct_progetto():
    from django.contrib.contenttypes.models import ContentType

    from ai.models import ProgettoChat
    return ContentType.objects.get_for_model(ProgettoChat).pk
