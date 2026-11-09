from django import template

register = template.Library()


@register.simple_tag
def contratti_dipendente(dipendente):
    from personale import contratti
    return {"vigore": contratti.in_vigore(dipendente), "tutti": list(dipendente.contratti.all()[:20])}
