from django import template

from fatturazione.operazioni import fatture_attive

register = template.Library()


@register.simple_tag
def ordine_fatturabile(ordine):
    return ordine.stato == "confermato" and not fatture_attive(ordine)


@register.simple_tag
def credito_cliente(fattura):
    """Il credito del cliente ancora da usare (acconti, eccedenze), se la fattura ha qualcosa da incassare."""
    from fatturazione import operazioni
    from fatturazione.models import Fattura
    if fattura.stato != Fattura.EMESSA or fattura.tipo == Fattura.NOTA_CREDITO or not fattura.cliente_id:
        return 0
    return sum((c.residuo for c in operazioni.crediti_disponibili(fattura.cliente, fattura.azienda)), 0)


@register.simple_tag
def posizione_contatto(contatto):
    """Per la scheda del contatto: posizione fiscale (scelta o automatica), dichiarazioni d'intento."""
    from fatturazione import posizioni
    from fatturazione.models import DichiarazioneIntento, PosizioneContatto, PosizioneFiscale
    if not (contatto.cliente if hasattr(contatto, "cliente") else True):
        return None
    scelta = PosizioneContatto.objects.filter(contatto=contatto).select_related("posizione").first()
    posizione = posizioni.posizione_di(contatto)
    return {"scelta": scelta, "posizione": posizione, "automatica": scelta is None and posizione is not None,
            "dichiarazione": posizioni.dichiarazione_attiva(contatto), "tutte": PosizioneFiscale.objects.filter(attiva=True),
            "dichiarazioni": DichiarazioneIntento.objects.filter(cliente=contatto).order_by("-dal")[:5]}
