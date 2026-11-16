from core.viste import ModelView, register

from .forms import ConnessioneForm, SportelloForm
from .models import Canale, Connessione, DomandaPortale, ModelloWhatsApp, Sportello, VoceConoscenza


@register
class CanaleView(ModelView):
    """Gestione dei canali per i responsabili (archiviare, rinominare); la conversazione è in /discuss/."""
    model = Canale
    slug = "canali"
    list_display = ["__str__", "tipo", "creato_da", "creato", "archiviato"]
    list_filter = ["tipo", "archiviato"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Canale", [("nome", "tipo"), "descrizione", "archiviato"])]
    readonly_fields = ["creato_da", "creato"]

    def get_queryset(self, request):
        return super().get_queryset(request).exclude(tipo=Canale.DIRETTO)    # i messaggi diretti restano privati


@register
class SportelloView(ModelView):
    """Le chat del sito: chi risponde, i testi e i domini ammessi. Il codice da incollare è nel dettaglio."""
    model = Sportello
    tra_aziende = True
    slug = "sportelli"
    list_display = ["nome", "attivo", "creato"]
    list_filter = ["attivo"]
    search_fields = ["nome"]
    form_class = SportelloForm
    form_layout = [("Sportello", ["nome", "benvenuto", "assenza", "operatori", "distribuzione", "domini", "privacy_url", "attivo"]),
                   ("Risposte con l'AI", ["modalita", "nome_ai", "istruzioni", ("risposte_per_chat", "risposte_al_giorno"), "azienda", "portale"]),
                   ("Conoscenza dalla wiki", ["spazi"])]

    def get_form_class(self, request=None):
        from django.apps import apps
        classe = super().get_form_class(request)
        if not apps.is_installed("wiki"):                  # senza wiki la sezione resta vuota: si toglie
            self.form_layout = [s for s in self.form_layout if s[0] != "Conoscenza dalla wiki"]
        return classe
    readonly_fields = ["creato"]


@register
class VoceConoscenzaView(ModelView):
    """Ciò che l'AI del sito può dire ai visitatori: domande frequenti e documenti approvati."""
    model = VoceConoscenza
    slug = "conoscenza"
    list_display = ["titolo", "tipo", "sportello", "attiva", "n_frammenti", "aggiornata"]
    list_filter = ["sportello", "tipo", "attiva"]
    search_fields = ["titolo", "testo"]
    form_layout = [("Voce", ["sportello", "tipo", "titolo", "testo", "attiva"])]

    def has_change_permission(self, request, obj=None):
        """Le pagine copiate dalla wiki si modificano nella wiki: qui si possono solo spegnere o togliere."""
        return super().has_change_permission(request, obj) and (obj is None or obj.pagina_wiki is None)


@register
class ConnessioneView(ModelView):
    """I numeri WhatsApp e i bot Telegram. I segreti si scrivono nel modulo e non si mostrano più."""
    model = Connessione
    api = False                   # contiene segreti o credenziali: niente API
    slug = "connessioni"
    list_display = ["nome", "tipo", "sportello", "sandbox", "attiva", "ultimo_evento"]
    list_filter = ["tipo", "sandbox", "attiva"]
    search_fields = ["nome"]
    form_class = ConnessioneForm
    form_layout = [("Connessione", [("nome", "tipo"), "sportello", ("sandbox", "attiva")]),
                   ("Credenziali, solo per una connessione vera", [("id_numero", "id_account"), "nuovo_token", "nuovo_segreto"])]
    readonly_fields = ["ultimo_evento"]


@register
class ModelloWhatsAppView(ModelView):
    """I testi approvati da Meta per ricontattare un cliente dopo le 24 ore."""
    model = ModelloWhatsApp
    slug = "modelliwa"
    list_display = ["nome", "lingua", "categoria", "stato", "connessione", "aggiornato"]
    list_filter = ["stato", "categoria", "connessione"]
    search_fields = ["nome", "corpo"]
    form_layout = [("Modello", ["connessione", ("nome", "lingua"), "categoria", "corpo"])]


@register
class DomandaPortaleView(ModelView):
    """Le domande dei clienti all'assistente del portale, con le risposte: per lo staff che cura la conoscenza."""
    model = DomandaPortale
    slug = "domande_portale"
    storico = False
    list_display = ["creata", "cliente", "utente", "domanda", "senza_risposta"]
    list_filter = ["senza_risposta", "sportello", "creata"]
    search_fields = ["domanda", "risposta", "cliente__nome"]
    form_layout = [("Domanda", [("cliente", "utente"), ("sportello", "creata"), "domanda", "risposta", "senza_risposta"])]
    readonly_fields = ["cliente", "utente", "sportello", "creata", "domanda", "risposta", "senza_risposta"]

    def get_queryset(self, request):
        """Solo i clienti dell'azienda corrente: le domande sono dati dei clienti."""
        azienda = getattr(request, "azienda", None)
        qs = super().get_queryset(request)
        return qs.filter(cliente__azienda=azienda) if azienda is not None else qs.none()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
