from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def pagina_wiki(context, pagina):
    from wiki import servizi
    utente = context["request"].user
    return {"html": servizi.rendi(pagina), "figlie": list(pagina.figlie.order_by("ordine", "titolo")), "percorso": pagina.percorso(),
            "versioni": list(pagina.versioni.select_related("autore")[:15]), "citata_da": servizi.citata_da(pagina),
            "scrive": servizi.puo_scrivere(utente, pagina.spazio)}
