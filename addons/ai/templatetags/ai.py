from django import template

from ai import markdown

register = template.Library()


@register.filter
def markdown_ai(testo):
    return markdown.rendi(testo)
