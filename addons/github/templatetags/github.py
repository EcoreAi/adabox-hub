from django import template

from ..models import Repository, ramo_suggerito, riferimento

register = template.Library()


@register.simple_tag
def github_del_compito(compito):
    return {"riferimento": riferimento(compito), "ramo": ramo_suggerito(compito),
            "repository": list(Repository.objects.filter(progetto_id=compito.progetto_id, attivo=True)),
            "collegamenti": list(compito.collegamenti_github.select_related("repository"))}
