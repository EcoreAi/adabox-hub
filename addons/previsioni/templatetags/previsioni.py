from django import template
from django.utils.safestring import mark_safe

from previsioni import esaurimenti
from previsioni.models import PrevisioneArticolo

register = template.Library()


@register.simple_tag(takes_context=True)
def previsioni_prodotto(context, prodotto):
    """Le previsioni salvate del prodotto per l'azienda corrente, una per magazzino (il totale per ultimo), con
    l'ultimo giorno dell'orizzonte; None se non ce ne sono."""
    azienda = getattr(context.get("request"), "azienda", None)
    if azienda is None:
        return None
    righe = sorted(PrevisioneArticolo.objects.filter(azienda=azienda, prodotto_pk=prodotto.pk),
                   key=lambda r: (r.magazzino_pk is None, r.magazzino))
    if not righe:
        return None
    for r in righe:
        r.fine_orizzonte = esaurimenti.fine_orizzonte(r)
        r.motivo = (r.affidabilita.get("motivi") or [""])[0]
    return {"righe": righe, "ferma_dal": esaurimenti.non_aggiornata_dal(azienda, righe)}


@register.simple_tag(takes_context=True)
def stato_previsioni(context):
    """Per la lista: quando sono state calcolate le previsioni dell'azienda e, se l'ultimo calcolo è fallito, da quando
    non sono aggiornate."""
    from django.db.models import Max
    azienda = getattr(context.get("request"), "azienda", None)
    if azienda is None:
        return None
    righe = PrevisioneArticolo.objects.filter(azienda=azienda)
    calcolata = righe.aggregate(m=Max("calcolata_il"))["m"]
    if calcolata is None:
        return None
    return {"calcolata_il": calcolata, "ferma_dal": esaurimenti.non_aggiornata_dal(azienda, righe.only("calcolata_il"))}


class _EntroNelForm(template.Node):
    """Tiene `?entro=N` nel form dei filtri della lista: il contenuto è la lista di base, a cui si aggiunge il campo
    nascosto subito dopo l'apertura del form."""
    def __init__(self, nodelist):
        self.nodelist = nodelist

    def render(self, context):
        html = self.nodelist.render(context)
        request, entro = context.get("request"), ""
        if request is not None:
            entro = request.GET.get("entro", "")
        if entro:
            from django.utils.html import format_html
            inizio = html.find('<form class="ui-filtri"')
            fine = html.find(">", inizio) + 1 if inizio >= 0 else 0
            if fine:
                html = html[:fine] + format_html('<input type="hidden" name="entro" value="{}">', entro) + html[fine:]
        return mark_safe(html)


@register.tag
def entro_nel_form(parser, token):
    nodelist = parser.parse(("fine_entro_nel_form",))
    parser.delete_first_token()
    return _EntroNelForm(nodelist)
