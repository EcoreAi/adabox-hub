from django import template

from ..models import FileProva, FileSharePoint

register = template.Library()


@register.simple_tag
def dati_sharepoint(collegamento):
    return {"allineati": FileSharePoint.objects.filter(collegamento=collegamento).count(),
            "prova": list(FileProva.objects.filter(collegamento=collegamento).order_by("percorso")[:200])
            if collegamento.modalita == collegamento.PROVA else []}


@register.filter
def byte(valore):
    return len(bytes(valore or b""))
