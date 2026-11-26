from django import template
from django.utils.safestring import mark_safe

from django.urls import reverse

from previsioni import esaurimenti, pagine
from previsioni.models import PrevisioneArticolo, StatoCalcolo

register = template.Library()


@register.simple_tag(takes_context=True)
def previsioni_prodotto(context, prodotto):
    """Le previsioni salvate del prodotto per l'azienda corrente, una per magazzino (il totale per ultimo), con
    l'ultimo giorno dell'orizzonte; None se non ce ne sono. Dalla vista «Articoli in esaurimento», con i suoi permessi
    e le sue regole di riga."""
    request = context.get("request")
    vista = pagine.vista_esaurimenti(request) if request is not None else None
    if vista is None:
        return None
    righe = sorted(vista.get_queryset(request).filter(prodotto_pk=prodotto.pk),
                   key=lambda r: (r.magazzino_pk is None, r.magazzino))
    avviso = esaurimenti.avviso(request.azienda)                # un calcolo non riuscito si dice anche senza righe
    if not righe and avviso is None:
        return None
    for r in righe:
        r.fine_orizzonte = esaurimenti.fine_orizzonte(r)
        r.motivo = (r.affidabilita.get("motivi") or [""])[0]
        basso, alto = esaurimenti.fascia_consumo(r)
        r.giacenza_testo, r.consumo_testo = esaurimenti.quantita(r.partenza), esaurimenti.quantita(r.consumo_mensile)
        r.fascia_consumo = f"{esaurimenti.quantita(basso)}–{esaurimenti.quantita(alto)}" if alto is not None else ""
    return {"righe": righe, "avviso": avviso, "unita": str(prodotto.unita) if getattr(prodotto, "unita_id", None) else "",
            "aggiorna": pagine.puo_aggiornare(request, StatoCalcolo.MAGAZZINO)}


@register.simple_tag(takes_context=True)
def vendite_prodotto_url(context, prodotto):
    """L'indirizzo della riga «Vendite previste» del prodotto, o "" se l'utente non vede le previsioni di Vendite."""
    request = context.get("request")
    if request is None or getattr(request, "azienda", None) is None or not pagine.vendite_prodotti_visibili(request):
        return ""
    return reverse("previsioni:prodotto_vendite", args=[prodotto.pk])


@register.simple_tag(takes_context=True)
def stato_previsioni(context):
    """Per la lista: quando sono state calcolate le previsioni dell'azienda, con quale modello e, se l'ultimo calcolo
    non è riuscito, l'avviso (anche senza righe); None se non c'è niente da dire."""
    from django.db.models import Max
    azienda = getattr(context.get("request"), "azienda", None)
    if azienda is None:
        return None
    righe = PrevisioneArticolo.objects.filter(azienda=azienda)
    calcolata = righe.aggregate(m=Max("calcolata_il"))["m"]
    avviso = esaurimenti.avviso(azienda)
    if calcolata is None and avviso is None:
        return None
    modello = righe.order_by("-calcolata_il").values_list("modello", flat=True).first() or ""
    return {"calcolata_il": calcolata, "modello": modello, "avviso": avviso}


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
