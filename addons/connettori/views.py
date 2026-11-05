from core.viste import ModelView, register

from . import eventi
from .models import ConsegnaWebhook, RiferimentoEsterno, Webhook


@register
class WebhookView(ModelView):
    model = Webhook
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
