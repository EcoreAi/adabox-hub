"""Collegamenti a SharePoint e file allineati. Il client secret si scrive nel modulo, si salva cifrato e non si mostra più."""
import random

from core import lavori
from core.viste import ModelView, register

from . import graph, prova, sincronia
from .forms import CollegamentoForm
from .models import CollegamentoSharePoint, FileProva, FileSharePoint

FILE_DI_PROVA = ["Offerta Rossi.txt", "Verbale riunione.txt", "Listino 2027.csv", "Note di progetto.md"]


@register
class CollegamentoSharePointView(ModelView):
    model = CollegamentoSharePoint
    api = False                   # contiene segreti o credenziali: niente API
    slug = "collegamenti"
    list_display = ["nome", "cartella", "verso", "modalita", "attivo", "ultimo_giro", "ultimo_esito"]
    list_filter = ["verso", "modalita", "attivo"]
    search_fields = ["nome", "sito", "percorso"]
    form_class = CollegamentoForm
    form_layout = [("Collegamento", ["nome", ("cartella", "verso"), ("modalita", "attivo")]),
                   ("Dove, su SharePoint", ["sito", ("libreria", "percorso")]),
                   ("Credenziali, solo per un collegamento vero", [("tenant", "client_id"), "nuovo_segreto"])]
    readonly_fields = ["ultimo_giro", "ultimo_esito"]
    company_field = "azienda"
    buttons = ["sincronizza", "verifica", "simula_nuovo", "simula_modifica"]
    ai_descrizione = ("I collegamenti tra le cartelle dei Documenti e le cartelle di SharePoint (Microsoft 365): verso, "
                      "sito, ultimo allineamento ed esito. Gli utenti dicono SharePoint, OneDrive aziendale o Teams.")

    def get_buttons(self, request, obj):
        voci = super().get_buttons(request, obj)
        return voci if obj.modalita == CollegamentoSharePoint.PROVA else [v for v in voci if not v[0].startswith("simula")]

    def sincronizza(self, request, obj):
        if not obj.attivo:
            return "Il collegamento è spento."
        lavori.accoda("sharepoint.sincronia.giro", collegamento_id=obj.pk, azienda=obj.azienda, utente=request.user, max_tentativi=3)
        return "Allineamento accodato: l'esito compare qui sotto."
    sincronizza.short_description = "Sincronizza ora"
    sincronizza.ai = False

    def verifica(self, request, obj):
        g = None
        try:
            g = sincronia.client(obj)
            nome = sincronia.verifica(obj, g)
        except graph.ErroreSharePoint as e:
            return str(e)
        finally:
            if g is not None:
                g.chiudi()
        return f"SharePoint risponde: il sito «{nome}» e la cartella ci sono, il collegamento funziona."
    verifica.short_description = "Verifica il collegamento"
    verifica.ai = False

    def simula_nuovo(self, request, obj):
        if obj.modalita != CollegamentoSharePoint.PROVA:
            return "Solo in prova."
        prova.prepara(obj)
        base = obj.percorso.strip("/")
        nome = f"{random.randint(100, 999)} {random.choice(FILE_DI_PROVA)}"
        prova.scrivi(obj, f"{base}/{nome}" if base else nome, f"Creato su SharePoint (finta): {nome}\n".encode())
        return f"Sulla SharePoint finta c'è il file «{nome}». Premi «Sincronizza ora»."
    simula_nuovo.short_description = "Simula un file nuovo su SharePoint"
    simula_nuovo.ai = False

    def simula_modifica(self, request, obj):
        base = obj.percorso.strip("/")
        file = FileProva.objects.filter(collegamento=obj, cartella=False)
        if base:
            file = file.filter(percorso__startswith=base + "/")
        f = file.order_by("?").first()
        if obj.modalita != CollegamentoSharePoint.PROVA or f is None:
            return "Nessun file da modificare."
        prova.scrivi(obj, f.percorso, bytes(f.contenuto) + "Riga aggiunta su SharePoint.\n".encode())
        return f"«{f.percorso}» modificato sulla SharePoint finta: premi «Sincronizza ora»."
    simula_modifica.short_description = "Simula una modifica su SharePoint"
    simula_modifica.ai = False


@register
class FileSharePointView(ModelView):
    model = FileSharePoint
    api = False
    storico = False
    slug = "file"
    list_display = ["percorso", "documento", "collegamento", "versione", "sincronizzato"]
    list_filter = ["collegamento"]
    search_fields = ["percorso", "documento__nome"]
    form_layout = [("File", ["collegamento", "documento", "percorso", ("versione", "sincronizzato")])]
    readonly_fields = ["collegamento", "documento", "percorso", "versione", "sincronizzato"]
    company_field = "azienda"
    ai_descrizione = "Quale documento dei Documenti corrisponde a quale file di SharePoint, e quando sono stati allineati."

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
