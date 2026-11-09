from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import redirect

from core.colori import sicuro
from core.viste import Inline, ModelView, register, schede

from . import flusso
from .models import Assenza, Dipendente, Posizione, Reparto, Timbratura, TipoAssenza, ContrattoLavoro, VoceRetributiva, DocumentoDipendente, RichiestaModifica


@register
class RepartoView(ModelView):
    model = Reparto
    slug = "reparti"
    list_display = ["nome", "responsabile"]
    search_fields = ["nome"]
    form_layout = [("Reparto", [("nome", "responsabile")])]
    company_field = "azienda"


@register
class PosizioneView(ModelView):
    """L'anagrafica delle posizioni: quante persone servono in ogni ruolo e quante ce ne sono."""
    model = Posizione
    slug = "posizioni"
    list_display = ["nome", "reparto", "organico", "occupati", "scoperti", "attiva"]
    list_filter = ["reparto", "attiva"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Posizione", [("nome", "reparto"), ("organico", "attiva"), "descrizione"])]
    company_field = "azienda"
    list_group_by = ["reparto"]
    api = True
    ai_descrizione = "Le posizioni dell'organico (ruoli) per reparto, con le persone previste e quelle in servizio."

    def col_occupati(self, obj):
        return obj.occupati()
    col_occupati.short_description = "In servizio"

    def col_scoperti(self, obj):
        mancano = obj.organico - obj.occupati()
        return mancano if mancano > 0 else "—"
    col_scoperti.short_description = "Da coprire"


@register
class TimbraturaView(ModelView):
    """Le timbrature: chi corregge a mano lascia nome e motivo."""
    model = Timbratura
    slug = "timbrature"
    list_display = ["il", "dipendente", "verso", "fonte", "inserita_da", "nota"]
    list_filter = ["dipendente", "verso", "fonte", "il"]
    search_fields = ["dipendente__nome", "dipendente__cognome", "nota"]
    form_layout = [("Timbratura", [("dipendente", "verso"), "il", "nota"])]
    readonly_fields = ["fonte", "inserita_da"]
    company_field = "azienda"
    list_group_by = ["dipendente", "il:giorno"]
    ai_descrizione = "Le timbrature di entrata e uscita dei dipendenti, dal chiosco, dal web o corrette a mano."

    def get_form_class(self, request=None):
        base = super().get_form_class(request)

        class Form(base):
            def clean(self):
                dati = super().clean()
                if not (dati.get("nota") or "").strip():
                    self.add_error("nota", "Scrivi il motivo della correzione.")
                return dati
        return Form

    def save_model(self, request, obj, form, change):
        obj.fonte, obj.inserita_da = "manuale", request.user
        super().save_model(request, obj, form, change)


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
    import_key = "codice_fiscale"
    list_display = ["__str__", "reparto", "ruolo", "responsabile", "tipo_contratto", "attivo"]
    list_filter = ["reparto", "tipo_contratto", "attivo"]
    search_fields = ["nome", "cognome", "codice_fiscale", "email", "ruolo"]
    form_layout = [
        ("Anagrafica", [("nome", "cognome"), ("codice_fiscale", "utente"), ("email", "telefono")]),
        ("Chiosco", ["badge"]),
        ("Lavoro", [("reparto", "posizione"), ("ruolo", "responsabile"), ("tipo_contratto", "ore_settimanali"),
                    ("data_assunzione", "data_cessazione"), ("giorni_ferie_annui", "ore_permesso_annue"), "attivo"]),
        ("Altro", ["@proprieta"]),
    ]
    company_field = "azienda"
    list_group_by = ["reparto", "tipo_contratto", "responsabile"]
    kanban_group = "reparto"
    kanban_fields = ["ruolo", "responsabile"]
    kanban_ricco = True
    chatter = True
    tracked_fields = ["reparto", "posizione", "ruolo", "responsabile", "tipo_contratto", "data_cessazione"]
    api = True


    def kanban_queryset(self, qs):
        return qs.select_related("utente", "reparto")

    def kanban_scheda(self, request, obj):
        esito = (*schede.FATTO, "Attivo") if obj.attivo else (*schede.FERMO, "Non attivo")
        return schede.scheda(esito, sottotitolo=obj.ruolo, righe=[obj.email] if obj.email else None,
                             etichette=[(obj.get_tipo_contratto_display(), "indaco")], persona=schede.persona(obj.utente))

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
    kanban_ricco = True
    kanban_colori = {"richiesta": "azzurro", "approvata": "verde", "rifiutata": "grigio", "annullata": "grigio"}
    chatter = True
    tracked_fields = ["stato", "dal", "al", "tipo"]
    buttons = ["approva", "rifiuta", "annulla"]
    actions = ["approva_selezionate"]


    def kanban_queryset(self, qs):
        return qs.select_related("dipendente", "tipo")

    def kanban_scheda(self, request, obj):
        esito = {Assenza.RICHIESTA: ("arancio", "icon-info", "Da approvare"), Assenza.APPROVATA: (*schede.FATTO, "Approvata"),
                 Assenza.RIFIUTATA: (*schede.FERMO, "Rifiutata"), Assenza.ANNULLATA: (*schede.FERMO, "Annullata")}[obj.stato]
        periodo = f"Dal {obj.dal:%d/%m/%Y} al {obj.al:%d/%m/%Y}" if obj.dal != obj.al else f"Il {obj.dal:%d/%m/%Y}"
        return schede.scheda(esito, sottotitolo=str(obj.dipendente), righe=[periodo], etichette=[(obj.tipo.nome, sicuro(obj.tipo.colore))])

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


@register
class ContrattoLavoroView(ModelView):
    """I contratti dei dipendenti: storico, condizioni, retribuzione. Quello in vigore aggiorna orario e ferie."""
    model = ContrattoLavoro
    slug = "contratti"
    company_field = "azienda"
    list_display = ["dipendente", "tipo", "ccnl", "livello", "dal", "al", "ore_settimanali"]
    list_filter = ["tipo", "dipendente"]
    search_fields = ["dipendente__nome", "dipendente__cognome", "ccnl", "livello", "mansione"]
    form_layout = [("Contratto", [("dipendente", "tipo"), ("dal", "al"), ("ccnl", "livello"), "mansione"]),
                   ("Orario e ferie", [("ore_settimanali", "giorni_ferie_annui"), "ore_permesso_annue"]),
                   ("Retribuzione", [("retribuzione_annua", "mensilita"), "note"])]
    inlines = [Inline(VoceRetributiva, "contratto", ["nome", "importo", "tipo"], titolo="Voci retributive", extra=0)]
    api = False                   # dati riservati: niente API
    ai_descrizione = "I contratti di lavoro dei dipendenti, dati riservati alle risorse umane."


@register
class DocumentoDipendenteView(ModelView):
    """Cedolini e documenti riservati: li carica l'ufficio, il dipendente li vede nel suo profilo."""
    model = DocumentoDipendente
    slug = "documenti"
    company_field = "azienda"
    list_display = ["dipendente", "tipo", "titolo", "periodo", "pubblicato_il", "letto_il"]
    list_filter = ["tipo", "dipendente"]
    search_fields = ["titolo", "dipendente__nome", "dipendente__cognome"]
    form_layout = [("Documento", [("dipendente", "tipo"), ("titolo", "periodo"), "file"])]
    api = False
    ai_descrizione = "I documenti riservati dei dipendenti (cedolini, CU): solo i dati, mai i file."


@register
class RichiestaModificaView(ModelView):
    """Le richieste dei dipendenti di correggere i loro dati: approva o rifiuta dalla scheda."""
    model = RichiestaModifica
    slug = "richieste"
    company_field = "azienda"
    list_display = ["creata", "dipendente", "email", "telefono", "stato"]
    list_filter = ["stato"]
    readonly_fields = ["dipendente", "email", "telefono", "altro", "stato", "decisa_da", "decisa_il", "creata"]
    form_layout = [("Richiesta", [("dipendente", "creata"), ("email", "telefono"), "altro", ("stato", "decisa_da")])]
    api = False
    ai_descrizione = "Le richieste dei dipendenti di modificare i propri dati anagrafici."

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False if obj is not None else super().has_change_permission(request, obj)
