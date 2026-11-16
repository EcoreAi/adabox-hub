from core.viste import ModelView, register

from .forms import ServizioForm
from .models import Casella, ServizioOAuth


@register
class ServizioView(ModelView):
    """L'applicazione dell'istanza su Google Cloud o Microsoft Entra: una per servizio, il segreto non si rilegge."""
    model = ServizioOAuth
    api = False                   # contiene segreti o credenziali: niente API
    slug = "servizi"
    list_display = ["tipo", "client_id", "tenant", "attivo"]
    form_class = ServizioForm
    form_layout = [("Applicazione", [("tipo", "attivo"), "client_id", "tenant", "nuovo_segreto"])]

    def has_add_permission(self, request):
        if ServizioOAuth.objects.count() >= len(ServizioOAuth._meta.get_field("tipo").choices):
            return False
        return super().has_add_permission(request)


@register
class CasellaView(ModelView):
    """Le caselle collegate, per l'amministratore: chi le ha, se funzionano. I token non si vedono mai."""
    model = Casella
    api = False
    slug = "caselle_utenti"
    list_display = ["utente", "email", "tipo", "posta", "calendario", "ultimo_giro", "ultimo_esito", "in_errore"]
    list_filter = ["tipo", "in_errore"]
    search_fields = ["email", "utente__username"]
    form_layout = [("Casella", [("utente", "tipo"), "email", ("posta", "calendario")])]
    readonly_fields = ["utente", "tipo", "email", "ultimo_giro", "ultimo_esito"]
    company_field = "azienda"

    def has_add_permission(self, request):
        return False                                    # si collega solo dalla propria pagina, con il consenso dell'utente
