from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import redirect

from core.viste import ModelView, register

from . import flusso
from .models import Assenza, Dipendente, Reparto, TipoAssenza


@register
class RepartoView(ModelView):
    model = Reparto
    slug = "reparti"
    list_display = ["nome", "responsabile"]
    search_fields = ["nome"]
    form_layout = [("Reparto", [("nome", "responsabile")])]
    company_field = "azienda"


@register
class TipoAssenzaView(ModelView):
    model = TipoAssenza
    slug = "tipi"
    list_display = ["nome", "unita", "saldo", "attivo"]
    form_layout = [("Tipo di assenza", [("nome", "unita"), ("saldo", "colore"), ("ordine", "attivo")])]


@register
class DipendenteView(ModelView):
    model = Dipendente
    slug = "dipendenti"
    list_display = ["__str__", "reparto", "ruolo", "responsabile", "tipo_contratto", "attivo"]
    list_filter = ["reparto", "tipo_contratto", "attivo"]
    search_fields = ["nome", "cognome", "codice_fiscale", "email", "ruolo"]
    form_layout = [
        ("Anagrafica", [("nome", "cognome"), ("codice_fiscale", "utente"), ("email", "telefono")]),
        ("Lavoro", [("reparto", "ruolo"), "responsabile", ("tipo_contratto", "ore_settimanali"),
                    ("data_assunzione", "data_cessazione"), ("giorni_ferie_annui", "ore_permesso_annue"), "attivo"]),
        ("Altro", ["@proprieta"]),
    ]
    company_field = "azienda"
    list_group_by = ["reparto", "tipo_contratto", "responsabile"]
    kanban_group = "reparto"
    kanban_fields = ["ruolo", "responsabile"]
    chatter = True
    tracked_fields = ["reparto", "ruolo", "responsabile", "tipo_contratto", "data_cessazione"]
    api = True

    def col___str__(self, obj):
        return str(obj)
    col___str__.short_description = "Dipendente"


@register
class AssenzaView(ModelView):
    model = Assenza
    slug = "assenze"
    list_display = ["dipendente", "tipo", "dal", "al", "durata", "stato"]
    list_filter = ["stato", "tipo", "dipendente", "dal"]
    search_fields = ["dipendente__nome", "dipendente__cognome", "motivo"]
    form_layout = [("Assenza", ["dipendente", "tipo", ("dal", "al"), "ore", "motivo"])]
    readonly_fields = ["stato", "decisa_da", "decisa_il", "nota_decisione"]
    company_field = "azienda"
    list_group_by = ["stato", "tipo", "dipendente", "dal:mese"]
    calendar_date = "dal"
    calendar_color = "stato"
    kanban_group = "stato"
    kanban_fields = ["tipo", "dal", "al"]
    chatter = True
    tracked_fields = ["stato", "dal", "al", "tipo"]
    buttons = ["approva", "rifiuta", "annulla"]
    actions = ["approva_selezionate"]

    def col_durata(self, obj):
        q = obj.quantita
        return f"{q:g} {'ore' if obj.tipo.unita == 'ore' else 'gg'}"
    col_durata.short_description = "Durata"

    def get_queryset(self, request):
        """L'ufficio del personale vede tutto; gli altri le proprie assenze e quelle dei collaboratori."""
        qs = super().get_queryset(request).select_related("dipendente", "tipo")
        if flusso.gestore(request.user):
            return qs
        u = request.user
        return qs.filter(Q(dipendente__utente=u) | Q(dipendente__responsabile__utente=u)
                         | Q(dipendente__reparto__responsabile__utente=u))

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato == Assenza.RICHIESTA)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            flusso.richiesta_inviata(obj, request.user)

    def get_buttons(self, request, obj):
        nomi = set()
        if obj.stato == Assenza.RICHIESTA and flusso.puo_decidere(request.user, obj):
            nomi |= {"approva", "rifiuta"}
        if obj.stato in (Assenza.RICHIESTA, Assenza.APPROVATA) and (
                obj.dipendente.utente_id == request.user.pk or flusso.gestore(request.user)):
            nomi.add("annulla")
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in nomi]

    def _decidi(self, request, obj, approvata):
        try:
            flusso.decidi(obj, request.user, approvata, request.POST.get("nota", ""))
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect(self.url("dettaglio", pk=obj.pk))
        return f"{obj} {'approvata' if approvata else 'rifiutata'}."

    def approva(self, request, obj):
        return self._decidi(request, obj, True)
    approva.short_description = "Approva"
    approva.permission = "view"                          # decide chi approva, non il permesso di modifica

    def rifiuta(self, request, obj):
        return self._decidi(request, obj, False)
    rifiuta.short_description = "Rifiuta"
    rifiuta.permission = "view"

    def annulla(self, request, obj):
        try:
            flusso.annulla(obj, request.user)
        except (ValidationError, PermissionDenied) as e:
            messages.error(request, " ".join(getattr(e, "messages", ["Non puoi annullarla."])))
            return redirect(self.url("dettaglio", pk=obj.pk))
        return f"{obj} annullata."
    annulla.short_description = "Annulla"
    annulla.permission = "view"

    def approva_selezionate(self, request, queryset):
        n = 0
        for a in queryset.filter(stato=Assenza.RICHIESTA).select_related("dipendente"):
            if flusso.puo_decidere(request.user, a):
                flusso.decidi(a, request.user, True)
                n += 1
        return f"Richieste approvate: {n}."
    approva_selezionate.short_description = "Approva"
    approva_selezionate.permission = "view"
