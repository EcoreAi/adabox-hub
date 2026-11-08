from core.viste import ModelView, register

from .forms import ProviderAccessoForm
from .models import AccessoPortale, IdentitaEsterna, ProviderAccesso


@register
class AccessoPortaleView(ModelView):
    """Chi dei clienti entra nel portale. Si invita e si sospende dalla scheda del contatto."""
    model = AccessoPortale
    slug = "accessi"
    list_display = ["utente", "contatto", "attivo", "ultimo_accesso", "invitato_il"]
    search_fields = ["utente__username", "contatto__nome"]
    readonly_fields = ["utente", "contatto", "invitato_da", "invitato_il"]
    form_layout = [("Accesso", [("utente", "contatto"), ("invitato_da", "invitato_il")])]
    ai_descrizione = "Gli accessi dei clienti al portale clienti: quale persona di quale cliente entra, se è attivo, l'ultimo accesso."

    def get_queryset(self, request):
        """Gli accessi dei contatti dell'azienda corrente (l'accesso non ha un'azienda propria: è quella del contatto)."""
        azienda = getattr(request, "azienda", None)
        qs = super().get_queryset(request).select_related("utente", "contatto")
        return qs.filter(contatto__azienda=azienda) if azienda is not None else qs.none()

    def has_add_permission(self, request):
        return False                                  # si crea con «Invita al portale» dal contatto

    def col_attivo(self, obj):
        return "sì" if obj.utente.is_active else "sospeso"
    col_attivo.short_description = "Attivo"

    def col_ultimo_accesso(self, obj):
        return obj.utente.last_login.strftime("%d/%m/%Y %H:%M") if obj.utente.last_login else "mai"
    col_ultimo_accesso.short_description = "Ultimo accesso"


@register
class ProviderAccessoView(ModelView):
    """Google e Microsoft per i clienti del portale: nella scheda l'indirizzo di ritorno da registrare nel servizio."""
    model = ProviderAccesso
    slug = "provider"
    list_display = ["tipo", "client_id", "attivo"]
    form_class = ProviderAccessoForm
    form_layout = [("Servizio", [("tipo", "attivo"), "client_id", "nuovo_segreto", "tenant"])]


@register
class IdentitaEsternaView(ModelView):
    """Gli account Google o Microsoft collegati: toglierne uno obbliga a ricollegarlo al prossimo accesso."""
    model = IdentitaEsterna
    slug = "account_collegati"
    list_display = ["utente", "tipo", "email", "collegata_il", "ultimo_accesso"]
    list_filter = ["tipo"]
    search_fields = ["email", "utente__username"]
    readonly_fields = ["utente", "tipo", "soggetto", "email", "collegata_il", "ultimo_accesso"]

    def has_add_permission(self, request):
        return False
