from django.utils import timezone

from core.viste import ModelView, register

from .models import ConsumoAI, Istanza, ModuloVendibile, Pacchetto, Piano, Richiesta, Suite


@register
class IstanzeView(ModelView):
    model = Istanza
    api = False                   # contiene segreti o credenziali: niente API
    slug = "istanze"
    list_display = ["cliente", "piano", "canone", "scadenza", "ultimo_contatto", "utenti_attivi", "ospitata", "attiva"]
    list_filter = ["piano", "ospitata", "attiva", "scadenza"]
    search_fields = ["cliente", "email", "url"]
    form_layout = [("Cliente", [("cliente", "email"), ("url", "ospitata")]),
                   ("Licenza", [("piano", "scadenza"), ("utenti", "grazia_giorni"), "suite", "moduli_extra", "funzioni_extra", "attiva"]),
                   ("Assistente AI (vuoto = come il piano)", [("ai_formula", "ai_ricarico"), ("ai_quota_utente", "ai_quota_istanza")]),
                   ("Stato", [("ultimo_contatto", "utenti_attivi"), "codice"]), ("Note", ["note"])]
    readonly_fields = ["ultimo_contatto", "utenti_attivi", "codice"]
    list_group_by = ["piano", "ospitata", "scadenza:mese"]
    chatter = True
    tracked_fields = ["piano", "scadenza", "utenti", "attiva", "ai_formula"]
    buttons = ["genera_token"]

    def col_canone(self, obj):
        return f"{obj.canone_mese():.2f} €"
    col_canone.short_description = "Canone al mese"

    def genera_token(self, request, obj):
        return (f"Token di {obj.cliente}: {obj.nuovo_token()} (si vede solo adesso: va in LICENZA_TOKEN sull'istanza; "
                f"quello di prima non vale più).")
    genera_token.short_description = "Genera il token"
    genera_token.rischio = "irreversibile"
    genera_token.ai = False


@register
class RichiesteView(ModelView):
    model = Richiesta
    slug = "richieste"
    list_display = ["creata", "istanza", "nome", "tipo", "utente", "stato"]
    list_filter = ["stato", "tipo", "istanza"]
    search_fields = ["nome", "slug", "nota"]
    form_layout = [("Richiesta", [("istanza", "nome"), ("tipo", "utente"), "creata", "nota", ("stato", "decisa_il"), "decisa_da"])]
    readonly_fields = ["istanza", "nome", "tipo", "utente", "creata", "nota", "stato", "decisa_il", "decisa_da"]
    list_group_by = ["stato", "istanza", "nome"]
    buttons = ["approva", "gestita", "rifiuta"]
    chatter = True
    tracked_fields = ["stato"]

    def has_add_permission(self, request):
        return False

    def get_buttons(self, request, obj):
        if obj.stato != Richiesta.NUOVA:
            return []
        fuori = "approva" if obj.tipo == Richiesta.DEMO else "gestita"     # una demo non entra in licenza
        return [(n, e) for n, e in super().get_buttons(request, obj) if n != fuori]

    def _decidi(self, request, obj, stato):
        obj.stato, obj.decisa_il, obj.decisa_da = stato, timezone.now(), request.user
        obj.save(update_fields=["stato", "decisa_il", "decisa_da"])

    def gestita(self, request, obj):
        self._decidi(request, obj, Richiesta.APPROVATA)
        return f"Demo di {obj.nome} per {obj.istanza} segnata come gestita."
    gestita.short_description = "Demo gestita"

    def approva(self, request, obj):
        if obj.tipo == Richiesta.SUITE:
            suite = Suite.objects.filter(slug=obj.slug).first()
            if suite is None:
                return f"La suite {obj.slug} non è più in vendita."
            obj.istanza.suite.add(suite)
            self._decidi(request, obj, Richiesta.APPROVATA)
            return f"Suite {suite} aggiunta a {obj.istanza}: alla prossima sincronizzazione arrivano le sue app e il dipartimento."
        modulo = ModuloVendibile.objects.filter(slug=obj.slug).first()
        if modulo is None:
            return f"Il modulo {obj.slug} non è più in vendita."
        obj.istanza.moduli_extra.add(modulo)
        self._decidi(request, obj, Richiesta.APPROVATA)
        return f"{modulo} aggiunto a {obj.istanza}: l'istanza lo installa alla prossima sincronizzazione."
    approva.short_description = "Approva e attiva"

    def rifiuta(self, request, obj):
        self._decidi(request, obj, Richiesta.RIFIUTATA)
        return f"Richiesta di {obj.nome} rifiutata."
    rifiuta.short_description = "Rifiuta"


@register
class PianiView(ModelView):
    model = Piano
    slug = "piani"
    list_display = ["nome", "prezzo_mese", "prezzo_utente_mese", "utenti", "ai_formula", "attivo"]
    list_filter = ["attivo", "ai_formula"]
    search_fields = ["nome"]
    form_layout = [("Piano", [("nome", "attivo"), ("prezzo_mese", "prezzo_utente_mese"), "utenti", "moduli", "descrizione"]),
                   ("Assistente AI", [("ai_formula", "ai_ricarico"), ("ai_quota_utente", "ai_quota_istanza")]),
                   ("Funzioni dei moduli", ["moduli_a_funzioni", "funzioni"])]


@register
class SuiteView(ModelView):
    model = Suite
    slug = "suite"
    list_display = ["nome", "slug", "prezzo_mese", "utenti", "in_catalogo", "ordine"]
    list_filter = ["in_catalogo"]
    search_fields = ["nome", "slug", "descrizione"]
    form_layout = [("Suite", [("nome", "slug"), ("prezzo_mese", "utenti"), ("in_catalogo", "ordine"), "moduli", "descrizione"])]


@register
class ModuliView(ModelView):
    model = ModuloVendibile
    slug = "moduli"
    list_display = ["nome", "slug", "categoria", "prezzo_mese", "application", "in_catalogo", "su_misura"]
    list_filter = ["categoria", "application", "in_catalogo", "su_misura"]
    search_fields = ["nome", "slug"]
    form_layout = [("Modulo", [("nome", "slug"), ("categoria", "prezzo_mese"), "riassunto", ("application", "in_catalogo", "su_misura")]),
                   ("Scheda nel catalogo", ["descrizione", "funzioni", "url_demo"])]
    readonly_fields = ["slug"]

    def has_add_permission(self, request):
        return False


@register
class PacchettiView(ModelView):
    model = Pacchetto
    slug = "pacchetti"
    list_display = ["modulo", "versione", "min_core", "dimensione", "pubblicato", "creato"]
    list_filter = ["modulo", "pubblicato"]
    search_fields = ["nome_file", "sha256"]
    form_layout = [("Pacchetto", [("modulo", "versione"), ("nome_file", "dimensione"), ("min_core", "creato"), "sha256", "pubblicato"])]
    readonly_fields = ["modulo", "versione", "nome_file", "dimensione", "min_core", "creato", "sha256"]

    def has_add_permission(self, request):
        return False


@register
class ConsumiAIView(ModelView):
    """Il consumo dell'assistente riferito dalle istanze, mese per mese: l'importo da fatturare con la formula a consumo
    e, con quella inclusa, quanta parte della quota è stata usata."""
    model = ConsumoAI
    storico = False
    slug = "consumi_ai"
    list_display = ["mese", "istanza", "formula", "costo", "costo_fornito", "sulla_quota", "importo", "utenti", "turni", "aggiornato"]
    list_filter = ["formula", "istanza", "mese"]
    search_fields = ["istanza__cliente"]
    form_layout = [("Consumo", [("istanza", "mese"), ("formula", "quota"), ("costo", "costo_fornito"), ("utenti", "turni"),
                                ("importo", "aggiornato")])]
    readonly_fields = ["istanza", "mese", "formula", "quota", "costo", "costo_fornito", "utenti", "turni", "importo", "aggiornato"]
    list_group_by = ["mese:mese", "istanza", "formula"]
    list_sum = ["costo_fornito", "importo"]

    def col_mese(self, obj):
        return f"{obj.mese:%m/%Y}"
    col_mese.short_description = "Mese"

    def col_sulla_quota(self, obj):
        return f"{obj.costo_fornito / obj.quota * 100:.0f}%" if obj.quota else "—"
    col_sulla_quota.short_description = "Sulla quota"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
