from django import template

register = template.Library()


@register.simple_tag
def testo_stampa(modello, campo, obj=None, azienda=None):
    """Un testo del modello di stampa con i segnaposto riempiti (HTML sicuro)."""
    from core import stampe
    return stampe.testo(modello, campo, obj, azienda)
