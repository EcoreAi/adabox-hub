from django.utils.html import format_html

from core.viste import Inline, ModelView, register, schede

from . import catalogo, immagini
from .models import Categoria, ComponenteKit, Confezione, ImmagineProdotto, Listino, PrezzoListino, Prodotto, UnitaMisura


class ImmaginiProdotto(Inline):
    """Dal telefono il campo propone subito la fotocamera o la galleria."""

    def formset_class(self, documento, azienda_id=None):
        formset = super().formset_class(documento, azienda_id)
        formset.form.base_fields["file"].widget.attrs.update(accept="image/*")
        return formset


@register
class ProdottoView(ModelView):
    model = Prodotto
    slug = "prodotti"
    list_display = ["miniatura", "nome", "codice", "tipo", "categoria", "prezzo_vendita", "aliquota_iva", "attivo"]
    list_filter = ["tipo", "categoria", "aliquota_iva", "attivo"]
    search_fields = ["nome", "codice", "codice_barre", "descrizione_vendita", "confezioni__codice_barre"]
    form_layout = [
        ("Prodotto", [("nome", "codice"), ("tipo", "categoria"), ("unita", "codice_barre"), ("unita_vendita", "unita_acquisto"), ("peso", "attivo"), "immagine"]),
        ("Prezzi", [("prezzo_vendita", "costo"), "aliquota_iva"]),
        ("Altro", ["descrizione_vendita", ("scorta_minima", "kit"), "@proprieta"]),
    ]
    inlines = [ImmaginiProdotto(ImmagineProdotto, "prodotto", ["file", "didascalia", "ordine"], titolo="Altre immagini", extra=0),
               Inline(Confezione, "prodotto", ["nome", "quantita", "codice_barre", "peso"], titolo="Confezioni", extra=0),
               Inline(ComponenteKit, "kit", ["componente", "quantita"], titolo="Componenti del kit", extra=0)]
    company_field = "azienda"
    sequence_field = ("codice", "prodotti.prodotto")
    list_group_by = ["tipo", "categoria", "aliquota_iva"]
    kanban_group = "categoria"
    kanban_fields = ["codice", "prezzo_vendita", "tipo"]
    kanban_ricco = True
    graph = {"tipi": ["barre", "torta"], "misure": ["count"], "per": ["categoria", "tipo", "aliquota_iva"]}
    chatter = True
    tracked_fields = ["prezzo_vendita", "costo", "aliquota_iva", "attivo"]
    import_key = "codice"
    api = True
    reports = [{"nome": "Scheda prodotto", "template": "prodotti/report/scheda.html"}]
    actions = ["stampa_catalogo"]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("immagini")

    def col_miniatura(self, obj):
        url = immagini.url(obj, 64)
        if not url:
            return format_html('<span class="ui-miniatura" aria-hidden="true"></span>')
        return format_html('<img class="ui-miniatura" src="{}" alt="" loading="lazy">', url)
    col_miniatura.short_description = ""

    def stampa_catalogo(self, request, queryset):
        """Catalogo in PDF dei prodotti scelti, con foto e prezzo, a griglia."""
        return catalogo.risposta(request, queryset)
    stampa_catalogo.short_description = "Stampa il catalogo"

    def formsets(self, request, obj, data=None, files=None):
        """Confezioni e componenti sono facoltativi: chi salva il prodotto senza mandarli (API, importazioni, Ada,
        vecchi form) li lascia come sono, invece di vedersi rifiutare il salvataggio."""
        tutti = super().formsets(request, obj, data, files)
        if data is None:
            return tutti
        return [(inline, fs) for inline, fs in tutti if f"{fs.prefix}-TOTAL_FORMS" in data]

    def kanban_queryset(self, qs):
        return qs.select_related("categoria").prefetch_related("immagini")

    def kanban_scheda(self, request, obj):
        esito = (*schede.FATTO, "Attivo") if obj.attivo else (*schede.FERMO, "Non attivo")
        return schede.scheda(esito, sottotitolo=obj.codice, valore=schede.euro(obj.prezzo_vendita),
                             immagine=immagini.url(obj, 600),
                             etichette=[(obj.get_tipo_display(), "azzurro" if obj.tipo == Prodotto.BENE else "viola")])



@register
class ListinoView(ModelView):
    model = Listino
    slug = "listini"
    import_key = "nome"
    list_display = ["nome", "attivo"]
    form_layout = [("Listino", ["nome", ("attivo", "iva_inclusa"), "note"])]
    company_field = "azienda"
    inlines = [Inline(PrezzoListino, "listino", ["prodotto", "quantita_minima", "prezzo", "valido_dal", "valido_al"], titolo="Prezzi")]
    api = True


@register
class CategoriaView(ModelView):
    model = Categoria
    slug = "categorie"
    list_display = ["nome"]
    search_fields = ["nome"]


@register
class UnitaView(ModelView):
    """Le unità di misura con categoria e fattore di conversione."""
    model = UnitaMisura
    slug = "unita"
    list_display = ["simbolo", "nome", "categoria", "fattore"]
    list_filter = ["categoria"]
    form_layout = [("Unità", [("simbolo", "nome"), ("categoria", "fattore")])]
