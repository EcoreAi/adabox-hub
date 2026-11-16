from django.utils import timezone

from core.viste import ModelView, register

from .models import Chiamata, ClientOAuth, ChatCollegata


class _SolaLettura:
    """Dati che nascono dal protocollo: si guardano, non si scrivono a mano."""
    api = False
    per_assistente = False
    storico = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@register
class CollegamentiView(_SolaLettura, ModelView):
    model = ChatCollegata
    slug = "collegamenti"
    company_field = "azienda"
    list_display = ["utente", "fornitore", "client", "creato", "ultimo_uso", "revocato"]
    list_filter = ["fornitore", "utente", "revocato"]
    search_fields = ["utente__username", "utente__last_name", "client__nome"]
    form_layout = [("Collegamento", [("utente", "fornitore"), ("client", "sola_lettura"), "app", ("creato", "ultimo_uso"),
                                     ("revocato", "revocato_da")])]
    readonly_fields = ["utente", "fornitore", "client", "sola_lettura", "app", "creato", "ultimo_uso", "revocato", "revocato_da"]
    list_group_by = ["utente", "fornitore"]
    buttons = ["scollega"]

    def get_buttons(self, request, obj):
        return super().get_buttons(request, obj) if obj.attivo else []

    def scollega(self, request, obj):
        obj.revoca(da=request.user)
        return f"{obj} scollegata il {timezone.localtime(obj.revocato):%d/%m/%Y alle %H:%M}: i suoi token non valgono più."
    scollega.short_description = "Scollega"
    scollega.permission = "delete"
    scollega.rischio = "irreversibile"
    scollega.ai = False


@register
class ChiamateView(_SolaLettura, ModelView):
    model = Chiamata
    slug = "chiamate"
    company_field = "azienda"
    list_display = ["creato", "utente", "collegamento", "strumento", "vista", "esito", "durata_ms", "mascherati"]
    list_filter = ["esito", "strumento", "utente", "creato"]
    search_fields = ["strumento", "vista", "motivo"]
    form_layout = [("Chiamata", [("creato", "utente"), "collegamento", ("strumento", "vista"), ("esito", "motivo"),
                                 ("durata_ms", "mascherati")])]
    readonly_fields = ["creato", "utente", "collegamento", "strumento", "vista", "esito", "motivo", "durata_ms", "mascherati"]
    list_group_by = ["utente", "strumento", "esito", "creato:mese"]


@register
class ClientView(_SolaLettura, ModelView):
    """Le chat che si sono presentate a questa istanza: sono dell'istanza, non di un'azienda."""
    model = ClientOAuth
    slug = "client"
    tra_aziende = True
    list_display = ["nome", "fornitore", "tipo", "creato", "ultimo_uso"]
    list_filter = ["fornitore", "tipo"]
    search_fields = ["nome", "client_id"]
    form_layout = [("Chat", [("nome", "fornitore"), ("tipo", "autenticazione"), "client_id", "redirect_uris",
                             ("creato", "letto"), "ultimo_uso"])]
    readonly_fields = ["nome", "fornitore", "tipo", "autenticazione", "client_id", "redirect_uris", "creato", "letto", "ultimo_uso"]
