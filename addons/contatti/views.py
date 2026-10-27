from core.viste import ModelView, register

from .models import Categoria, Contatto


@register
class ContattoView(ModelView):
    model = Contatto
    slug = "contatti"
    list_display = ["nome", "codice", "tipo", "citta", "telefono", "email"]
    list_filter = ["tipo", "cliente", "fornitore", "categorie", "responsabile"]
    search_fields = ["nome", "codice", "email", "partita_iva", "codice_fiscale", "citta"]
    ordering = ["nome"]
    form_layout = [
        ("Anagrafica", ["tipo", "nome", ("societa", "ruolo"), ("cliente", "fornitore"), ("categorie", "responsabile")]),
        ("Recapiti", [("email", "pec"), ("telefono", "cellulare"), "sito", ("indirizzo", "cap"),
                      ("citta", "provincia", "nazione")]),
        ("Dati fiscali", [("partita_iva", "codice_fiscale", "codice_sdi")]),
        ("Altro", ["note", "attivo", "@proprieta"]),
    ]
    readonly_fields = ["codice"]
    company_field = "azienda"
    sequence_field = ("codice", "contatti.contatto")
    list_group_by = ["tipo", "citta", "responsabile"]
    kanban_group = "tipo"
    kanban_fields = ["email", "telefono", "citta"]
    chatter = True
    tracked_fields = ["nome", "email", "telefono", "cliente", "fornitore", "responsabile", "attivo"]
    import_key = "codice"
    reports = [{"nome": "Scheda contatto", "template": "contatti/report/contatto.html"}]
    actions = ["archivia"]
    api = True

    def archivia(self, request, queryset):
        n = queryset.update(attivo=False)
        return f"Contatti archiviati: {n}."
    archivia.short_description = "Archivia"


@register
class CategoriaView(ModelView):
    model = Categoria
    slug = "categorie"
    list_display = ["nome", "colore"]
    search_fields = ["nome"]
    api = True
