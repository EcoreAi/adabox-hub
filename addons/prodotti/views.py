from django.core.exceptions import ValidationError
from django.utils.html import format_html

from core.viste import Inline, ModelView, register, schede

from . import catalogo, immagini, varianti
from .models import (Attributo, AttributoProdotto, Categoria, CodiceBarre, CodiceCliente, ComponenteKit, Confezione,
                     ImmagineProdotto, Listino, PrezzoListino, Prodotto, UnitaMisura, ValoreAttributo)


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
    list_filter = ["tipo", "categoria", "aliquota_iva", "con_varianti", "attivo"]
    search_fields = ["nome", "codice", "codice_barre", "descrizione_vendita", "confezioni__codice_barre", "codici_barre__codice",
                     "codici_cliente__codice"]
    form_layout = [
        ("Prodotto", [("nome", "codice"), ("tipo", "categoria"), ("unita", "codice_barre"), ("unita_vendita", "unita_acquisto"), ("peso", "attivo"), "immagine"]),
        ("Prezzi", [("prezzo_vendita", "costo"), "aliquota_iva"]),
        ("Varianti", [("con_varianti", "variante_di"), "valori"]),
        ("Altro", ["descrizione_vendita", ("scorta_minima", "kit"), "alternativi", "@proprieta"]),
    ]
    inlines = [ImmaginiProdotto(ImmagineProdotto, "prodotto", ["file", "didascalia", "ordine"], titolo="Altre immagini", extra=0),
               Inline(AttributoProdotto, "prodotto", ["attributo", "valori"], titolo="Attributi delle varianti", extra=0),
               Inline(CodiceBarre, "prodotto", ["codice", "nota"], titolo="Altri codici a barre", extra=0),
               Inline(CodiceCliente, "prodotto", ["cliente", "codice", "descrizione"], titolo="Codici dei clienti", extra=0),
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
    buttons = ["genera_varianti"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("variante_di").prefetch_related("immagini", "variante_di__immagini")

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
    stampa_catalogo.permission = "view"

    def genera_varianti(self, request, obj):
        """Una variante per ogni combinazione dei valori scelti negli attributi."""
        try:
            create, disattivate = varianti.genera(obj)
        except ValidationError as e:
            return " ".join(e.messages)
        testo = f"Varianti create: {create}." if create else "Nessuna variante nuova: c'erano già tutte."
        return testo + (f" Disattivate {disattivate} varianti che non hanno più la loro combinazione." if disattivate else "")
    genera_varianti.short_description = "Genera varianti"
    genera_varianti.permission = "add"

    def get_buttons(self, request, obj):
        return [(n, e) for n, e in super().get_buttons(request, obj) if n != "genera_varianti" or obj.con_varianti]

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
class AttributoView(ModelView):
    """Taglia, colore, materiale…: con i loro valori, da scegliere sui prodotti con varianti."""
    model = Attributo
    slug = "attributi"
    list_display = ["nome", "ordine"]
    search_fields = ["nome", "valori__nome"]
    form_layout = [("Attributo", [("nome", "ordine")])]
    inlines = [Inline(ValoreAttributo, "attributo", ["nome", "codice", "sovrapprezzo", "ordine"], titolo="Valori")]
    import_key = "nome"


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
