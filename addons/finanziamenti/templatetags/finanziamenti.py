from django import template

from finanziamenti import piano

register = template.Library()


@register.simple_tag
def piano_di(finanziamento):
    return piano.riepilogo(finanziamento)
