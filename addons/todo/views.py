from django.db.models import Q
from django.utils.html import format_html

from core import chatter
from core.colori import sicuro
from core.viste import ModelView, register, schede

from .models import Attivita, Tag

PILL_STATO = {Attivita.APERTA: "ui-pill-info", Attivita.IN_CORSO: "ui-pill-warn",
              Attivita.FATTA: "ui-pill-ok", Attivita.ANNULLATA: "ui-pill-neutral"}


@register
class AttivitaView(ModelView):
    model = Attivita
    slug = "attivita"
    list_display = ["titolo", "numero", "scadenza", "assegnatario", "stato"]
    list_filter = ["stato", "assegnatario", "tag"]
    search_fields = ["titolo", "descrizione", "numero"]
    ordering = ["-scadenza", "-creato"]
    form_layout = [
        ("Generale", ["titolo", ("scadenza", "assegnatario"), "descrizione"]),
        ("Classificazione", ["tag", "stato", "@proprieta"]),
    ]
    readonly_fields = ["numero", "creato"]
    company_field = "azienda"
    sequence_field = ("numero", "todo.attivita")
    chatter = True
    tracked_fields = ["stato", "assegnatario", "scadenza"]
    list_group_by = ["stato", "assegnatario", "scadenza:mese"]
    kanban_group = "stato"
    kanban_ordini = [("scadenza", "Scadenza")]
    kanban_valori_chiusi = ("fatta", "annullata")
    kanban_fields = ["numero", "scadenza", "assegnatario"]
    kanban_ricco = True
    kanban_colori = {"aperta": "indaco", "in_corso": "azzurro", "fatta": "verde", "annullata": "grigio"}
    calendar_date = "scadenza"
    calendar_color = "stato"
    graph = {"tipi": ["barre", "torta", "linee"], "misure": ["count"], "per": ["stato", "assegnatario", "scadenza:mese"]}
    import_key = "numero"
    reports = [{"nome": "Scheda attività", "template": "todo/report/attivita.html"}]
    actions = ["archivia"]
    buttons = ["segna_fatta"]
    api = True


    def kanban_queryset(self, qs):
        return qs.select_related("assegnatario").prefetch_related("tag")

    def kanban_scheda(self, request, obj):
        esito = {Attivita.FATTA: (*schede.FATTO, "Fatta"), Attivita.ANNULLATA: (*schede.FERMO, "Annullata")}.get(obj.stato) or schede.entro(obj.scadenza)
        return schede.scheda(esito, sottotitolo=obj.numero, etichette=[(t.nome, sicuro(t.colore)) for t in obj.tag.all()], persona=schede.persona(obj.assegnatario))

    def get_queryset(self, request):
        """Si vedono le attività proprie (assegnate o create) e quelle senza titolare; tutte con vedi_tutte_attivita."""
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser or user.has_perm("todo.vedi_tutte_attivita"):
            return qs
        return qs.filter(Q(assegnatario=user) | Q(creato_da=user) | Q(assegnatario=None, creato_da=None))

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creato_da = request.user
        super().save_model(request, obj, form, change)

    def col_stato(self, obj):
        return format_html('<span class="ui-pill {}">{}</span>', PILL_STATO[obj.stato], obj.get_stato_display())
    col_stato.short_description = "Stato"

    def _cambia_stato(self, request, obj, stato):
        """Cambio di stato da codice: si traccia a mano nel chatter (save_model non passa di qui)."""
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.stato = stato
        obj.save(update_fields=["stato"])
        chatter.traccia(obj, vecchi, request.user)

    def archivia(self, request, queryset):
        righe = list(queryset.exclude(stato=Attivita.ANNULLATA))
        for obj in righe:
            self._cambia_stato(request, obj, Attivita.ANNULLATA)
        return f"Attività archiviate: {len(righe)}."
    archivia.short_description = "Archivia"

    def segna_fatta(self, request, obj):
        self._cambia_stato(request, obj, Attivita.FATTA)
        return f"«{obj}» segnata come fatta."
    segna_fatta.short_description = "Segna fatta"


@register
class TagView(ModelView):
    model = Tag
    list_display = ["nome", "colore"]
    search_fields = ["nome"]
    api = True
