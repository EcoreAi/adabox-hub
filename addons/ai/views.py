from core import cifratura
from core.viste import Inline, ModelView, register

from .forms import AssistenteForm, ChiaveAziendaForm, PianificataForm, ProgettoChatForm, ProviderForm, ServerMCPForm, ServizioVoceForm
from .models import (AnelloCatena, Assistente, ChiaveAzienda, Modello, Pianificata, Profilo, Proposta, Provider, MemoriaUtente, ProgettoChat, ServerMCP, ServizioVoce, StrumentoSpento,
                     ValutazioneRisposta, Turno)


@register
class ProviderView(ModelView):
    model = Provider
    api = False                   # contiene segreti o credenziali: niente API
    slug = "provider"
    list_display = ["nome", "tipo", "chiave", "locale", "attivo"]
    form_class = ProviderForm
    form_layout = [("Provider", [("nome", "tipo"), "base_url", ("nuova_chiave", "togli_chiave"), ("locale", "attivo")])]

    def layout_dettaglio(self):
        """Nella scheda niente campi del form per la chiave: la chiave mascherata e i modelli stanno nella sezione sotto."""
        via = {"nuova_chiave", "togli_chiave"}
        return [(t, [r for r in ([c for c in riga if c not in via] if isinstance(riga, (list, tuple)) else ([] if riga in via else [riga])
                                 for riga in righe) if r]) for t, righe in super().layout_dettaglio()]

    def col_chiave(self, obj):
        try:
            return cifratura.mascherato(cifratura.decifra(obj.chiave_cifrata)) or "—"
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
    col_chiave.short_description = "Chiave"


@register
class ChiaveAziendaView(ModelView):
    model = ChiaveAzienda
    api = False                   # contiene segreti o credenziali: niente API
    tra_aziende = True
    slug = "chiavi"
    list_display = ["provider", "azienda", "chiave"]
    form_class = ChiaveAziendaForm
    form_layout = [("Chiave dell'azienda", [("provider", "azienda"), "chiave"])]

    def col_chiave(self, obj):
        try:
            return cifratura.mascherato(cifratura.decifra(obj.chiave_cifrata))
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
    col_chiave.short_description = "Chiave"


@register
class ModelloView(ModelView):
    model = Modello
    slug = "modelli"
    list_display = ["etichetta", "provider", "id_api", "contesto", "prezzo_input", "prezzo_output", "livello_chat", "attivo"]
    list_filter = ["provider", "attivo", "residenza_ue"]
    search_fields = ["etichetta", "id_api"]
    form_layout = [("Modello", [("provider", "id_api"), "etichetta", ("contesto", "max_output")]),
                   ("Prezzi in dollari per milione di token", [("prezzo_input", "prezzo_output"),
                                                               ("prezzo_cache_scrittura", "prezzo_cache_lettura")]),
                   ("Capacità", [("strumenti", "visione", "ragionamento"), ("residenza_ue", "attivo")]),
                   ("Nella chat", [("livello_chat", "sceglibile")])]


@register
class ProfiloView(ModelView):
    model = Profilo
    tra_aziende = True
    slug = "profili"
    list_display = ["nome", "compito", "app", "azienda", "effort", "catena_modelli", "attivo"]
    list_filter = ["compito", "attivo"]
    form_layout = [("Profilo", [("nome", "compito"), ("app", "azienda"), ("effort", "max_token"), "attivo"])]
    inlines = [Inline(AnelloCatena, "profilo", ["modello", "ordine"], titolo="Catena dei modelli (in ordine)")]

    def col_catena_modelli(self, obj):
        return " → ".join(a.modello.etichetta for a in obj.catena.select_related("modello")) or "—"
    col_catena_modelli.short_description = "Catena"


@register
class ConsumiView(ModelView):
    """Ogni chiamata ai modelli (turni della chat, titoli, pianificate): token, costo, esito."""
    model = Turno
    storico = False
    tra_aziende = True
    slug = "consumi"
    verbose_name_plural = "consumi"
    list_display = ["iniziato", "utente", "azienda", "compito", "modello", "passi", "costo", "protetti", "stato"]
    list_filter = ["compito", "stato", "modello", "azienda", "iniziato"]
    search_fields = ["utente__username", "testo", "errore"]
    form_layout = [("Turno", [("iniziato", "finito"), ("utente", "azienda"), ("compito", "modello"),
                              ("stato", "passi"), ("costo", "uso"), "errore"])]
    readonly_fields = ["iniziato", "finito", "utente", "azienda", "compito", "modello", "stato", "passi", "costo",
                       "uso", "errore"]
    list_group_by = ["iniziato:mese", "utente", "modello", "compito", "azienda"]
    list_sum = ["costo"]
    graph = {"tipi": ["barre", "linee", "torta"], "misure": ["sum:costo", "count"],
             "per": ["iniziato:mese", "utente", "modello", "compito"]}

    def col_costo(self, obj):
        return f"{obj.costo:.4f} $"
    col_costo.short_description = "Costo"

    def col_protetti(self, obj):
        return (obj.provenienza or {}).get("pii") or "—"
    col_protetti.short_description = "Dati protetti"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@register
class PianificataView(ModelView):
    funzione = "pianificate"
    """Le attività che l'assistente esegue da solo: ognuno vede le proprie, gli amministratori tutte."""
    model = Pianificata
    tra_aziende = True
    slug = "pianificate"
    list_display = ["nome", "quando", "attiva", "prossima", "esito"]
    list_filter = ["attiva", "ricorrenza"]
    search_fields = ["nome", "istruzioni"]
    form_class = PianificataForm
    form_layout = [("Attività", ["nome", "istruzioni", ("ambito", "progetto")]),
                   ("Quando", [("ricorrenza", "alle"), "giorni", ("giorno_mese", "ogni_ore", "minuti_prima")]),
                   ("Risultato (sempre anche nella sua chat)", [("in_discuss", "per_email"), "attiva"])]
    readonly_fields = ["utente", "prossima", "ultima", "esito", "errori", "conversazione"]
    buttons = ["esegui_ora", "sospendi", "riattiva"]

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None:
            return base
        from . import aree
        progetti = aree.visibili(request.user, getattr(request, "azienda", None))
        return type("PianificataFormUtente", (base,), {"progetti_utente": progetti})

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(utente=request.user)

    def save_model(self, request, obj, form, change):
        from .pianificate import calcola_prossima
        if not change:
            obj.utente, obj.azienda = request.user, getattr(request, "azienda", None)
        obj.prossima = calcola_prossima(obj) if obj.attiva else None
        if obj.attiva:
            obj.errori = 0
        super().save_model(request, obj, form, change)

    def col_quando(self, obj):
        return obj.frequenza()
    col_quando.short_description = "Quando"

    def col_conversazione(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html
        if not obj.conversazione_id:
            return "—"
        return format_html('<a href="{}">Apri la chat dei risultati</a>', reverse("ai:conversazione",
                                                                                   args=[obj.conversazione_id]))
    col_conversazione.short_description = "Risultati"

    def get_buttons(self, request, obj):
        nascosto = "sospendi" if not obj.attiva else "riattiva"
        return [(n, e) for n, e in super().get_buttons(request, obj) if n != nascosto]

    def esegui_ora(self, request, obj):
        from core import lavori
        lavori.accoda("ai.pianificate.esegui_id", pianificata_id=obj.pk, utente=request.user)
        return "Esecuzione avviata: il risultato arriva nella chat dei risultati tra poco."
    esegui_ora.short_description = "Esegui ora"

    def sospendi(self, request, obj):
        obj.attiva, obj.prossima = False, None
        obj.save(update_fields=["attiva", "prossima"])
        return f"«{obj}» sospesa."
    sospendi.short_description = "Sospendi"

    def riattiva(self, request, obj):
        from .pianificate import calcola_prossima
        obj.attiva, obj.errori, obj.prossima = True, 0, calcola_prossima(obj)
        obj.save(update_fields=["attiva", "errori", "prossima"])
        return f"«{obj}» riattivata: prossima esecuzione {obj.frequenza()}."
    riattiva.short_description = "Riattiva"


@register
class RegistroModificheView(ModelView):
    funzione = "scritture"
    """Registro delle modifiche proposte dall'assistente: chi, cosa, quando, esito (solo lettura)."""
    model = Proposta
    storico = False
    tra_aziende = True
    slug = "registro"
    verbose_name = "modifica dell'assistente"
    verbose_name_plural = "registro delle modifiche"
    list_display = ["creata", "utente", "azienda", "titolo", "rischio", "stato", "decisa"]
    list_filter = ["stato", "rischio", "utente", "azienda", "creata"]
    search_fields = ["titolo", "esito", "utente__username"]
    list_group_by = ["stato", "utente", "creata:mese"]
    form_layout = [("Proposta", [("creata", "decisa"), ("utente", "azienda"), "titolo", ("rischio", "stato"),
                                 "strumento", "argomenti", "dettagli", "riepilogo", "esito", "url"])]
    readonly_fields = ["creata", "decisa", "utente", "azienda", "titolo", "rischio", "stato", "strumento", "argomenti",
                       "dettagli", "riepilogo", "esito", "url"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@register
class AssistenteView(ModelView):
    funzione = "assistenti"
    """Assistenti configurabili: istruzioni, strumenti e modello propri; quello di un'app risponde nelle chat
    limitate a quell'app e fa da esperto per gli altri."""
    model = Assistente
    slug = "assistenti"
    list_display = ["nome", "app", "predefinito", "profilo", "n_strumenti", "attivo"]
    list_filter = ["attivo", "app"]
    search_fields = ["nome", "descrizione", "istruzioni"]
    form_class = AssistenteForm
    form_layout = [("Assistente", [("nome", "app"), "descrizione", ("predefinito", "attivo"), "istruzioni"]),
                   ("Strumenti e modello", ["strumenti", ("profilo", "gruppi")]),
                   ("Qualità", ["domande_oro"])]

    def col_n_strumenti(self, obj):
        return len(obj.strumenti) if obj.strumenti else "tutti"
    col_n_strumenti.short_description = "Strumenti"


@register
class ValutazioniView(ModelView):
    """I pollici sulle risposte, con la domanda: per capire dove l'assistente sbaglia. Si leggono e basta."""
    model = ValutazioneRisposta
    slug = "valutazioni"
    storico = False
    list_display = ["creata", "voto", "commento", "utente"]
    list_filter = ["voto", "creata"]
    search_fields = ["commento", "messaggio__testo"]
    form_layout = [("Valutazione", [("creata", "voto"), ("utente", "commento")])]
    readonly_fields = ["creata", "voto", "utente", "commento"]
    company_field = "azienda"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class _SoloMie(ModelView):
    """Personali: anche un amministratore vede solo le sue."""
    company_field = "azienda"
    storico = False
    personale = True

    def get_queryset(self, request):
        return super().get_queryset(request).filter(utente=request.user)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.utente = request.user
        super().save_model(request, obj, form, change)


@register
class MemoriaView(_SoloMie):
    funzione = "memoria"
    """Ciò che Ada ricorda di te in questa azienda: lo vedi tutto, lo cancelli quando vuoi."""
    model = MemoriaUtente
    slug = "memoria"
    list_display = ["testo", "creata"]
    search_fields = ["testo"]
    form_layout = [("Da ricordare", ["testo"])]
    readonly_fields = ["creata"]
    ai_descrizione = "Le cose che l'utente ha chiesto ad Ada di ricordare."


@register
class ProgettoChatView(_SoloMie):
    funzione = "aree_di_lavoro"
    """Chat raggruppate con istruzioni e file comuni."""
    model = ProgettoChat
    slug = "progetti"
    form_class = ProgettoChatForm
    form_layout = [("Area di lavoro", ["nome", "istruzioni", ("ambito", "cartella_documenti")]), ("App collegate", ["app_collegate"]),
                   ("Condivisione", ["membri"])]

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None:
            return base
        from . import archivio
        from . import aree
        from .pagine import app_selezionabili
        azienda = getattr(request, "azienda", None)
        return type("ProgettoChatFormUtente", (base,), {"cartelle": archivio.cartelle(request.user, azienda),
                                                        "app": [(a["slug"], a["label"]) for a in app_selezionabili(request.user)],
                                                        "candidati": aree.candidati(azienda, request.user) if azienda else None})

    # condivisa: i membri la vedono (dettaglio, file), ma solo chi l'ha creata la modifica o la elimina
    def get_queryset(self, request):
        from . import aree
        return ModelView.get_queryset(self, request).filter(pk__in=aree.visibili(request.user, getattr(request, "azienda", None)).values("pk"))

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.utente_id == request.user.pk)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or (obj.utente_id == request.user.pk and not obj.personale))

    def save_model(self, request, obj, form, change):
        from . import aree
        super().save_model(request, obj, form, change)
        if "membri" in form.cleaned_data:
            aree.imposta_membri(obj, form.cleaned_data["membri"])

    def col_condivisa(self, obj):
        n = obj.membri.count()
        return f"con {n} {'persona' if n == 1 else 'persone'}" if n else "no"
    col_condivisa.short_description = "Condivisa"

    def col_di(self, obj):
        return obj.utente.get_full_name() or obj.utente.username
    col_di.short_description = "Di"

    def layout_dettaglio(self):                      # cartella e membri si vedono nella sezione dell'area, con nomi veri
        via = {"cartella_documenti", "membri"}
        sezioni = [(t, [[c for c in riga if c not in via] for riga in righe]) for t, righe in super().layout_dettaglio()]
        return [(t, [r for r in righe if r]) for t, righe in sezioni if any(righe)]
    list_display = ["nome", "di", "condivisa", "creato"]
    search_fields = ["nome", "istruzioni"]
    readonly_fields = ["creato"]


@register
class ServerMCPView(ModelView):
    funzione = "mcp"
    """I sistemi esterni di cui Ada usa gli strumenti. Gli strumenti si accendono uno per uno, dopo averli letti."""
    model = ServerMCP
    api = False                   # contiene segreti o credenziali: niente API
    slug = "mcp"
    list_display = ["nome", "url", "token", "attivo", "aggiornato", "ultimo_errore"]
    form_class = ServerMCPForm
    form_layout = [("Server", ["nome", "url", "rete_interna", "attivo", "nuovo_token"])]
    company_field = "azienda"
    storico = False
    personale = True
    buttons = ["leggi_strumenti"]

    def layout_dettaglio(self):
        return [(t, [[c for c in riga if c != "nuovo_token"] for riga in righe if riga != ["nuovo_token"]]) for t, righe in super().layout_dettaglio()]

    def col_token(self, obj):
        try:
            return cifratura.mascherato(cifratura.decifra(obj.token_cifrato)) or "—"
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
    col_token.short_description = "Token"

    def leggi_strumenti(self, request, obj):
        from . import mcp
        try:
            voci = mcp.aggiorna(obj)
        except mcp.ErroreMCP as e:
            return f"Strumenti non letti: {e}"
        return f"Letti {len(voci)} strumenti. Quelli nuovi sono spenti: leggili e accendi solo quelli che servono."
    leggi_strumenti.short_description = "Leggi gli strumenti dal server"
    leggi_strumenti.ai = False


@register
class ServizioVoceView(ModelView):
    funzione = "voce"
    """I servizi che leggono le risposte ad alta voce: Kokoro in locale o un fornitore cloud con la sua chiave."""
    model = ServizioVoce
    api = False                   # contiene segreti o credenziali: niente API
    slug = "voce"
    tra_aziende = True
    list_display = ["nome", "tipo", "azienda", "chiave", "attivo"]
    form_class = ServizioVoceForm
    form_layout = [("Servizio", [("nome", "tipo"), ("azienda", "attivo"), "nuova_chiave", "regione"]),
                   ("Voci (vuoto = quelle consigliate)", [("modello",), ("voce_it", "voce_en")])]
    storico = False
    personale = True
    buttons = ["prova"]

    def layout_dettaglio(self):
        return [(t, [[c for c in riga if c != "nuova_chiave"] for riga in righe if riga != ["nuova_chiave"]]) for t, righe in super().layout_dettaglio()]

    def col_chiave(self, obj):
        if obj.locale:
            return "—"
        try:
            return cifratura.mascherato(obj.chiave()) or "manca"
        except cifratura.SegretoIlleggibile:
            return "illeggibile"
    col_chiave.short_description = "Chiave"

    def prova(self, request, obj):
        from . import voce
        try:
            for lingua, frase in (("it", "Buongiorno, sono Ada."), ("en", "Hello, I am Ada.")):
                voce.sintetizza(obj, frase, lingua)
        except voce.ErroreVoce as e:
            return f"Prova non riuscita: {e}"
        return "Prova riuscita: il servizio legge in italiano e in inglese."
    prova.short_description = "Prova il servizio"
    prova.ai = False


@register
class StrumentiSpentiView(ModelView):
    """Gli strumenti spenti a mano, in sola lettura: si spengono e riaccendono dalla pagina «Strumenti». La vista c'è
    perché i cambi finiscano nel registro delle modifiche."""
    model = StrumentoSpento
    api = False
    slug = "strumenti_spenti"
    list_display = ["nome", "azienda", "spento_da", "spento_il"]
    list_filter = ["azienda"]
    search_fields = ["nome"]
    readonly_fields = ["nome", "azienda", "spento_da", "spento_il"]
    form_layout = [("Strumento spento", [("nome", "azienda"), ("spento_da", "spento_il")])]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

