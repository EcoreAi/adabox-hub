from core.viste import ModelView, register

from .forms import ConnessioneForm
from .models import Canale, Connessione, Sportello, VoceConoscenza


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
    slug = "sportelli"
    list_display = ["nome", "attivo", "creato"]
    list_filter = ["attivo"]
    search_fields = ["nome"]
    form_layout = [("Sportello", ["nome", "benvenuto", "assenza", "operatori", "domini", "privacy_url", "attivo"]),
                   ("Risposte con l'AI", ["modalita", "nome_ai", "istruzioni", ("risposte_per_chat", "risposte_al_giorno"), "azienda"])]
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


@register
class ConnessioneView(ModelView):
    """I numeri WhatsApp e i bot Telegram. I segreti si scrivono nel modulo e non si mostrano più."""
    model = Connessione
    slug = "connessioni"
    list_display = ["nome", "tipo", "sportello", "sandbox", "attiva", "ultimo_evento"]
    list_filter = ["tipo", "sandbox", "attiva"]
    search_fields = ["nome"]
    form_class = ConnessioneForm
    form_layout = [("Connessione", [("nome", "tipo"), "sportello", ("sandbox", "attiva")]),
                   ("Credenziali, solo per una connessione vera", ["id_numero", "nuovo_token", "nuovo_segreto"])]
    readonly_fields = ["ultimo_evento"]
