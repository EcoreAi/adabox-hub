from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import redirect

from core.viste import Inline, ModelView, register
from personale.models import Dipendente

from . import flusso
from .models import CategoriaSpesa, NotaSpese, RigaSpesa


def euro(valore):
    from core.viste.gruppi import numero
    return f"{numero(valore)} €"


@register
class CategoriaView(ModelView):
    model = CategoriaSpesa
    slug = "categorie"
    list_display = ["nome", "limite", "ricevuta_obbligatoria", "chilometrica", "tariffa_km", "attiva"]
    form_layout = [("Categoria", ["nome", ("limite", "ricevuta_obbligatoria"), ("chilometrica", "tariffa_km"), "attiva"])]


@register
class NotaView(ModelView):
    model = NotaSpese
    slug = "note"
    list_display = ["numero", "titolo", "dipendente", "totale", "stato", "inviata_il"]
    list_filter = ["stato", "dipendente", "inviata_il"]
    search_fields = ["numero", "titolo", "dipendente__nome", "dipendente__cognome"]
    form_layout = [("Nota spese", [("titolo", "dipendente"), "note"])]
    readonly_fields = ["numero", "stato", "totale", "inviata_il", "decisa_da", "nota_decisione", "rimborsata_il"]
    company_field = "azienda"
    sequence_field = ("numero", "spese.nota")
    inlines = [Inline(RigaSpesa, "nota", ["data", "categoria", "descrizione", "km", "importo", "ricevuta"],
                      titolo="Spese", extra=2)]
    list_group_by = ["stato", "dipendente", "inviata_il:mese"]
    list_sum = ["totale"]
    kanban_group = "stato"
    kanban_fields = ["dipendente", "totale"]
    chatter = True
    tracked_fields = ["stato", "totale"]
    buttons = ["invia", "approva", "rifiuta", "riapri", "rimborsa"]
    actions = ["rimborsa_selezionate"]
    reports = [{"nome": "Stampa", "template": "spese/report/nota.html"}]

    def col_totale(self, obj):
        return euro(obj.totale)
    col_totale.short_description = "Totale"

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("dipendente")
        if flusso.gestore(request.user):
            return qs
        u = request.user
        return qs.filter(Q(dipendente__utente=u) | Q(dipendente__responsabile__utente=u)
                         | Q(dipendente__reparto__responsabile__utente=u))

    def _mio(self, request):
        return Dipendente.objects.filter(utente=request.user, attivo=True).first()

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None or flusso.gestore(request.user):
            return base

        class Form(base):                               # il dipendente scrive le proprie note
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields.pop("dipendente", None)
        return Form

    def has_add_permission(self, request):
        return super().has_add_permission(request) and (flusso.gestore(request.user) or self._mio(request) is not None)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.modificabile)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or obj.modificabile)

    def save_model(self, request, obj, form, change):
        if not change and not obj.dipendente_id:
            mio = self._mio(request)
            if mio is None:
                raise PermissionDenied
            obj.dipendente = mio
        super().save_model(request, obj, form, change)

    def dopo_righe(self, request, obj):
        obj.ricalcola()

    def totali(self, obj):
        return [("Totale", euro(obj.totale))]

    def get_buttons(self, request, obj):
        u, nomi = request.user, set()
        proprietario = obj.dipendente.utente_id == u.pk
        if obj.stato == NotaSpese.BOZZA and (proprietario or flusso.gestore(u)):
            nomi.add("invia")
        if obj.stato == NotaSpese.INVIATA and flusso.puo_decidere(u, obj) and (not proprietario or u.is_superuser):
            nomi |= {"approva", "rifiuta"}
        if obj.stato == NotaSpese.RIFIUTATA and (proprietario or flusso.gestore(u)):
            nomi.add("riapri")
        if obj.stato == NotaSpese.APPROVATA and flusso.gestore(u):
            nomi.add("rimborsa")
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in nomi]

    def _esegui(self, request, obj, funzione, *args):
        try:
            funzione(obj, request.user, *args)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
            return redirect(self.url("dettaglio", pk=obj.pk))
        return None

    def invia(self, request, obj):
        return self._esegui(request, obj, flusso.invia) or f"{obj} inviata per l'approvazione."
    invia.short_description = "Invia per l'approvazione"
    invia.permission = "view"

    def approva(self, request, obj):
        return self._esegui(request, obj, flusso.decidi, True) or f"{obj} approvata."
    approva.short_description = "Approva"
    approva.permission = "view"

    def rifiuta(self, request, obj):
        return self._esegui(request, obj, flusso.decidi, False, request.POST.get("nota", "")) or f"{obj} rifiutata."
    rifiuta.short_description = "Rifiuta"
    rifiuta.permission = "view"

    def riapri(self, request, obj):
        obj.stato = NotaSpese.BOZZA
        obj.save(update_fields=["stato"])
        return "Nota riportata in bozza: correggi e reinvia."
    riapri.short_description = "Riporta in bozza"
    riapri.permission = "view"

    def rimborsa(self, request, obj):
        return self._esegui(request, obj, flusso.rimborsa) or f"{obj} rimborsata."
    rimborsa.short_description = "Segna rimborsata"
    rimborsa.permission = "view"

    def rimborsa_selezionate(self, request, queryset):
        if not flusso.gestore(request.user):
            raise PermissionDenied
        note = list(queryset.filter(stato=NotaSpese.APPROVATA).select_related("dipendente"))
        for n in note:
            flusso.rimborsa(n, request.user)
        return f"Note rimborsate: {len(note)}."
    rimborsa_selezionate.short_description = "Segna rimborsate"
    rimborsa_selezionate.permission = "view"
