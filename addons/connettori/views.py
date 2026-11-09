import random

from django.apps import apps

from core import lavori
from core.viste import ModelView, register

from . import eventi, sincronia
from .forms import CollegamentoForm
from .models import CollegamentoEsterno, ConsegnaWebhook, RecordProva, RiferimentoEsterno, Webhook
from .sistemi import hubspot
from .sistemi import prova as sistema_di_prova
from .sistemi.base import ErroreConnettore

NOMI_DI_PROVA = ["Giulia Ferrari", "Marco Galli", "Sara Conti", "Luca Moretti", "Elena Rizzo", "Paolo Greco"]
DITTE_DI_PROVA = ["Verdi Arredamenti Srl", "Officine Lombarde Spa", "Bianco Logistica Srl", "Studio Neri Associati"]


@register
class WebhookView(ModelView):
    model = Webhook
    api = False                   # contiene segreti o credenziali: niente API
    slug = "webhook"
    list_display = ["nome", "url", "attivo", "fallimenti_di_fila", "disattivato_il"]
    list_filter = ["attivo"]
    search_fields = ["nome", "url", "eventi"]
    form_layout = [("Webhook", ["nome", "url", "eventi", "attivo"])]
    readonly_fields = ["fallimenti_di_fila", "disattivato_il"]
    company_field = "azienda"
    buttons = ["prova", "nuovo_segreto"]

    def prova(self, request, obj):
        eventi.prova(obj)
        return f"Prova accodata per {obj.host}: l'esito è tra le consegne."
    prova.short_description = "Invia una prova"
    prova.ai = False

    def nuovo_segreto(self, request, obj):
        obj.nuovo_segreto()
        obj.save(update_fields=["segreto_cifrato"])
        return "Nuova chiave generata: aggiornala anche sul sistema che riceve."
    nuovo_segreto.short_description = "Cambia la chiave"
    nuovo_segreto.rischio = "irreversibile"
    nuovo_segreto.ai = False


@register
class ConsegnaView(ModelView):
    model = ConsegnaWebhook
    api = False                   # contiene segreti o credenziali: niente API
    storico = False
    slug = "consegne"
    list_display = ["evento", "webhook", "stato", "tentativi", "risposta", "errore", "creata", "consegnata_il"]
    list_filter = ["stato", "webhook", "creata"]
    search_fields = ["evento", "errore", "uid"]
    form_layout = [("Consegna", ["webhook", "evento", ("stato", "tentativi"), ("risposta", "errore"), ("creata", "consegnata_il")])]
    readonly_fields = ["webhook", "evento", "stato", "tentativi", "risposta", "errore", "creata", "consegnata_il"]
    company_field = "azienda"
    buttons = ["riprova"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_buttons(self, request, obj):
        return super().get_buttons(request, obj) if obj.stato == ConsegnaWebhook.FALLITA else []

    def riprova(self, request, obj):
        if obj.stato != ConsegnaWebhook.FALLITA:
            return "Si riprovano solo le consegne fallite."
        ConsegnaWebhook.objects.filter(pk=obj.pk).update(stato=ConsegnaWebhook.IN_CODA, tentativi=0, errore="")
        eventi._accoda(obj)
        return "Consegna rimessa in coda."
    riprova.short_description = "Riprova"
    riprova.permission = "connettori.change_webhook"
    riprova.ai = False


@register
class RiferimentoView(ModelView):
    model = RiferimentoEsterno
    slug = "riferimenti"
    list_display = ["sistema", "content_type", "object_id", "id_esterno", "creato"]
    list_filter = ["sistema", "content_type"]
    search_fields = ["id_esterno", "sistema"]
    form_layout = [("Collegamento", ["sistema", ("content_type", "object_id"), "id_esterno"])]
    readonly_fields = ["creato"]
    company_field = "azienda"
    api = True


@register
class CollegamentoView(ModelView):
    """Il legame con un sistema esterno. Il token si scrive nel modulo, si salva cifrato e non si mostra più."""
    model = CollegamentoEsterno
    slug = "collegamenti"
    list_display = ["sistema", "modalita", "comanda", "attivo", "ultimo_giro", "ultimo_esito"]
    list_filter = ["sistema", "attivo"]
    form_class = CollegamentoForm
    form_layout = [("Collegamento", [("sistema", "modalita"), "comanda", ("aziende", "opportunita"), "attivo"]),
                   ("Credenziali, solo per un collegamento vero", ["nuovo_token"])]
    readonly_fields = ["ultimo_giro", "ultimo_esito"]
    company_field = "azienda"
    buttons = ["sincronizza", "verifica", "simula_nuovo", "simula_modifica"]

    def has_add_permission(self, request):
        azienda = getattr(request, "azienda", None)
        if azienda is not None and CollegamentoEsterno.objects.filter(azienda=azienda).count() >= len(CollegamentoEsterno.SISTEMI):
            return False                                   # uno per sistema
        return super().has_add_permission(request)

    def get_buttons(self, request, obj):
        voci = super().get_buttons(request, obj)
        return voci if obj.modalita == CollegamentoEsterno.PROVA else [v for v in voci if not v[0].startswith("simula")]

    def sincronizza(self, request, obj):
        if not apps.is_installed("contatti"):
            return "Serve il modulo Contatti."
        if not obj.attivo:
            return "Il collegamento è spento."
        if obj.comanda == CollegamentoEsterno.ESTERNO:
            lavori.accoda("connettori.sincronia.giro", collegamento_id=obj.pk, azienda=obj.azienda, max_tentativi=3)
            return "Lettura accodata: l'esito compare qui sotto."
        from contatti.models import Contatto
        persone = Contatto.objects.filter(azienda=obj.azienda, tipo=Contatto.PERSONA).exclude(email="")
        aziende = Contatto.objects.filter(azienda=obj.azienda, tipo=Contatto.AZIENDA) if obj.aziende else Contatto.objects.none()
        voci = list(aziende.values_list("pk", flat=True)) + list(persone.values_list("pk", flat=True))
        for pk in voci:
            lavori.accoda("connettori.sincronia.scrivi_fuori", collegamento_id=obj.pk, contatto_id=pk, azienda=obj.azienda, max_tentativi=5)
        testo = f"Scrittura accodata per {len(voci)} contatti"
        if obj.opportunita and sincronia.crm_attivo():
            from crm.models import Opportunita
            opportunita = list(Opportunita.objects.filter(azienda=obj.azienda).values_list("pk", flat=True))
            for pk in opportunita:
                lavori.accoda("connettori.sincronia.scrivi_opportunita", collegamento_id=obj.pk, opportunita_id=pk, azienda=obj.azienda,
                              max_tentativi=5)
            testo += f" e {len(opportunita)} opportunità"
        return testo + "."
    sincronizza.short_description = "Sincronizza ora"
    sincronizza.ai = False

    def verifica(self, request, obj):
        try:
            sincronia.client(obj).verifica()
        except ErroreConnettore as e:
            return str(e)
        return f"{obj.get_sistema_display()} risponde: il collegamento funziona."
    verifica.short_description = "Verifica il collegamento"
    verifica.ai = False

    def simula_nuovo(self, request, obj):
        """Sul sistema finto: una persona nuova e, se il collegamento le comprende, la sua azienda e un'opportunità."""
        if obj.modalita != CollegamentoEsterno.PROVA:
            return "Solo in prova."
        nome = random.choice(NOMI_DI_PROVA)
        primo, _, secondo = nome.partition(" ")
        persona = sistema_di_prova.scrivi(obj, {"firstname": primo, "lastname": secondo,
                                                "email": f"{primo}.{secondo}.{random.randint(100, 999)}@example.com".lower(),
                                                "phone": f"+39 02 {random.randint(1000000, 9999999)}"})
        cosa = [f"la persona «{nome}»"]
        if obj.aziende:
            ditta = random.choice(DITTE_DI_PROVA)
            azienda = sistema_di_prova.scrivi(obj, {"name": ditta, "domain": f"{ditta.split()[0].lower()}.example.com", "city": "Milano"},
                                              tipo=hubspot.AZIENDE)
            sistema_di_prova.associa(obj, persona, azienda)
            cosa.append(f"l'azienda «{ditta}»")
        if obj.opportunita:
            fase = random.choice(sistema_di_prova.FASI[:5])
            trattativa = sistema_di_prova.scrivi(obj, {"dealname": f"Fornitura per {secondo}", "amount": str(random.randint(10, 90) * 100),
                                                       "pipeline": "default", "dealstage": fase[0]}, tipo=hubspot.OPPORTUNITA)
            sistema_di_prova.associa(obj, trattativa, azienda if obj.aziende else persona)
            cosa.append("un'opportunità")
        return f"Sul sistema finto: {', '.join(cosa)}. Premi «Sincronizza ora»."
    simula_nuovo.short_description = "Simula un cliente nuovo"
    simula_nuovo.ai = False

    def simula_modifica(self, request, obj):
        record = RecordProva.objects.filter(collegamento=obj, tipo=hubspot.CONTATTI).first() if obj.modalita == CollegamentoEsterno.PROVA else None
        if record is None:
            return "Nessun record da modificare."
        sistema_di_prova.scrivi(obj, {"jobtitle": random.choice(["Responsabile acquisti", "Titolare", "Amministrazione"])}, record.id_esterno)
        trattativa = RecordProva.objects.filter(collegamento=obj, tipo=hubspot.OPPORTUNITA).first()
        if trattativa is not None:
            fasi = [f[0] for f in sistema_di_prova.FASI]          # avanza di una fase, fino a «vinta»
            attuale = trattativa.proprieta.get("dealstage")
            prossima = fasi[min(fasi.index(attuale) + 1 if attuale in fasi else 0, fasi.index("closedwon"))]
            sistema_di_prova.scrivi(obj, {"dealstage": prossima}, trattativa.id_esterno, hubspot.OPPORTUNITA)
        return "Record modificato sul sistema finto: premi «Sincronizza ora»."
    simula_modifica.short_description = "Simula una modifica"
    simula_modifica.ai = False
