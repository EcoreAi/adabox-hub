from django import template

from ..forms import ConfigContoForm
from ..models import ConfigConto, CoordinateBancarie, Mandato

register = template.Library()


@register.simple_tag
def config_distinte(conto):
    config = ConfigConto.objects.filter(conto=conto).first() or ConfigConto(conto=conto)
    return {"config": config, "form": ConfigContoForm(instance=config)}


@register.simple_tag
def coordinate_contatto(contatto):
    return {"coordinate": CoordinateBancarie.objects.filter(contatto=contatto).first(),
            "mandati": list(Mandato.objects.filter(contatto=contatto, attivo=True))}
