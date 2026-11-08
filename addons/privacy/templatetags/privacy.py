from django import template

register = template.Library()


@register.simple_tag
def stato_privacy(contatto):
    from privacy import servizi
    from privacy.models import Anonimizzazione, Consenso
    return {"consensi": servizi.stato_consensi(contatto), "fonti": Consenso.FONTI,
            "anonimizzato": Anonimizzazione.objects.filter(contatto=contatto).first()}
