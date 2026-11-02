from django.utils import timezone

from core import chatter
from core.viste import ModelView, register

from . import validatori, vies

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
        ("Dati fiscali", [("partita_iva", "codice_fiscale", "codice_sdi"), "pubblica_amministrazione",
                          ("vies_valido", "vies_il")]),
        ("Altro", ["note", "attivo", "@proprieta"]),
    ]
    readonly_fields = ["codice", "vies_valido", "vies_il"]
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
    buttons = ["verifica_vies"]
    api = True

    def get_buttons(self, request, obj):
        pulsanti = super().get_buttons(request, obj)
        return pulsanti if obj.partita_iva and obj.nazione in validatori.UE else [
            (n, e) for n, e in pulsanti if n != "verifica_vies"]

    def verifica_vies(self, request, obj):
        try:
            esito = vies.controlla(obj.nazione, obj.partita_iva)
        except vies.ViesNonDisponibile:
            return "Il VIES non risponde in questo momento: riprova più tardi."
        vecchi = chatter.valori(obj, ["vies_valido"])
        obj.vies_valido, obj.vies_il = esito["valido"], timezone.now()
        obj.save(update_fields=["vies_valido", "vies_il"])
        chatter.traccia(obj, vecchi, request.user)
        if not esito["valido"]:
            return f"{obj.nazione}{obj.partita_iva} non è attiva nel VIES: niente operazioni intracomunitarie senza IVA."
        return f"Partita IVA valida nel VIES{': ' + esito['nome'] if esito['nome'] else ''}."
    verifica_vies.short_description = "Verifica nel VIES"
    verifica_vies.ai = False
    verifica_vies.permission = "view"

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
