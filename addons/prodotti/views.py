from core.viste import Inline, ModelView, register

from .models import Categoria, Listino, PrezzoListino, Prodotto, UnitaMisura


@register
class ProdottoView(ModelView):
    model = Prodotto
    slug = "prodotti"
    list_display = ["nome", "codice", "tipo", "categoria", "prezzo_vendita", "aliquota_iva", "attivo"]
    list_filter = ["tipo", "categoria", "aliquota_iva", "attivo"]
    search_fields = ["nome", "codice", "codice_barre", "descrizione_vendita"]
    form_layout = [
        ("Prodotto", [("nome", "codice"), ("tipo", "categoria"), ("unita", "codice_barre"), "attivo"]),
        ("Prezzi", [("prezzo_vendita", "costo"), "aliquota_iva"]),
        ("Altro", ["descrizione_vendita", "scorta_minima", "@proprieta"]),
    ]
    company_field = "azienda"
    sequence_field = ("codice", "prodotti.prodotto")
    list_group_by = ["tipo", "categoria", "aliquota_iva"]
    kanban_group = "categoria"
    kanban_fields = ["codice", "prezzo_vendita", "tipo"]
    graph = {"tipi": ["barre", "torta"], "misure": ["count"], "per": ["categoria", "tipo", "aliquota_iva"]}
    chatter = True
    tracked_fields = ["prezzo_vendita", "costo", "aliquota_iva", "attivo"]
    import_key = "codice"
    api = True


@register
class ListinoView(ModelView):
    model = Listino
    slug = "listini"
    list_display = ["nome", "attivo"]
    form_layout = [("Listino", ["nome", "attivo", "note"])]
    company_field = "azienda"
    inlines = [Inline(PrezzoListino, "listino", ["prodotto", "quantita_minima", "prezzo"], titolo="Prezzi")]
    api = True


@register
class CategoriaView(ModelView):
    model = Categoria
    slug = "categorie"
    list_display = ["nome"]
    search_fields = ["nome"]


@register
class UnitaView(ModelView):
    model = UnitaMisura
    slug = "unita"
    list_display = ["simbolo", "nome"]
