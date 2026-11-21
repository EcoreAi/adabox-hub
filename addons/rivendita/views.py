from django import forms
from django.utils import timezone

from core import cifratura
from core.viste import Inline, ModelView, register

from .models import ChiaveAIIstanza, ConsumoAI, Istanza, ModelloFornito, ModuloVendibile, Pacchetto, Piano, ProviderFornito, Richiesta, Suite


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
                   ("Assistente AI (vuoto = come il piano)", [("ai_formula", "ai_ricarico"), ("ai_quota_utente", "ai_quota_istanza"), "ai_tetto_istanza"]),
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
                   ("Assistente AI", [("ai_formula", "ai_ricarico"), ("ai_quota_utente", "ai_quota_istanza"), "ai_tetto_istanza", "ai_solo_forniti"]),
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


class ProviderFornitoForm(forms.ModelForm):
    """La chiave si scrive qui, si salva cifrata e non si rilegge."""
    nuova_chiave = forms.CharField(label="chiave API", required=False, strip=True,
                                   widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
                                   help_text="lascia vuoto per non cambiarla; arriva alle istanze alla prossima sincronizzazione")

    class Meta:
        model = ProviderFornito
        fields = ["codice", "nome", "tipo", "base_url", "attivo"]

    def save(self, commit=True):
        if self.cleaned_data.get("nuova_chiave"):
            self.instance.chiave_cifrata = cifratura.cifra(self.cleaned_data["nuova_chiave"])
        return super().save(commit)


@register
class ProviderFornitiView(ModelView):
    """I fornitori di modelli che diamo ai clienti con la nostra chiave: da qui arrivano a tutte le istanze."""
    model = ProviderFornito
    api = False                   # contiene segreti o credenziali: niente API
    slug = "provider_ai"
    list_display = ["nome", "codice", "tipo", "chiave", "attivo"]
    form_class = ProviderFornitoForm
    form_layout = [("Provider", [("nome", "codice"), ("tipo", "attivo"), "base_url", "nuova_chiave"])]
    inlines = [Inline(ModelloFornito, "provider", ["id_api", "etichetta", "prezzo_input", "prezzo_output", "prezzo_cache_scrittura",
                                                   "prezzo_cache_lettura", "contesto", "max_output", "livello_chat", "visione",
                                                   "ragionamento", "residenza_ue", "attivo"], titolo="Modelli e prezzi ($ per milione di token)")]

    def layout_dettaglio(self):
        return [(t, [r for r in righe if r != "nuova_chiave"]) for t, righe in super().layout_dettaglio()]

    def col_chiave(self, obj):
        try:
            return cifratura.mascherato(cifratura.decifra(obj.chiave_cifrata)) or "manca"
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
    col_chiave.short_description = "Chiave"


class ChiaveAIIstanzaForm(forms.ModelForm):
    nuova_chiave = forms.CharField(label="chiave API", required=False, strip=True,
                                   widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
                                   help_text="di norma la chiave virtuale del gateway per questo cliente; lascia vuoto per non cambiarla")

    class Meta:
        model = ChiaveAIIstanza
        fields = ["provider", "istanza", "base_url"]

    def clean(self):
        dati = super().clean()
        if not (dati.get("nuova_chiave") or self.instance.chiave_cifrata):
            self.add_error("nuova_chiave", "Scrivi la chiave.")
        return dati

    def save(self, commit=True):
        if self.cleaned_data.get("nuova_chiave"):
            self.instance.chiave_cifrata = cifratura.cifra(self.cleaned_data["nuova_chiave"])
        return super().save(commit)


@register
class ChiaviAIIstanzeView(ModelView):
    """La chiave di un provider fornito per un solo cliente (es. la chiave virtuale del gateway), al posto di quella comune."""
    model = ChiaveAIIstanza
    api = False                   # contiene segreti o credenziali: niente API
    slug = "chiavi_ai"
    list_display = ["istanza", "provider", "chiave", "base_url"]
    list_filter = ["provider", "istanza"]
    form_class = ChiaveAIIstanzaForm
    form_layout = [("Chiave dell'istanza", [("istanza", "provider"), "base_url", "nuova_chiave"])]

    def layout_dettaglio(self):
        return [(t, [r for r in righe if r != "nuova_chiave"]) for t, righe in super().layout_dettaglio()]

    def col_chiave(self, obj):
        try:
            return cifratura.mascherato(cifratura.decifra(obj.chiave_cifrata))
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
    col_chiave.short_description = "Chiave"
