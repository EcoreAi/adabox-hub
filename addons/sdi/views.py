from django.shortcuts import redirect
from django.urls import reverse

from core.viste import ModelView, register

from .models import NotificaSdi, Trasmissione


@register
class TrasmissioneView(ModelView):
    model = Trasmissione
    slug = "trasmissioni"
    list_display = ["nome_file", "fattura", "cliente", "stato", "canale", "inviata_il", "identificativo_sdi"]
    list_filter = ["stato", "canale", "inviata_il"]
    search_fields = ["nome_file", "identificativo_sdi", "fattura__numero", "fattura__cliente__nome"]
    form_layout = [("Trasmissione", [("fattura", "nome_file"), ("stato", "canale"), ("identificativo_sdi", "inviata_il"),
                                     "esito_il"])]
    readonly_fields = ["fattura", "nome_file", "stato", "canale", "identificativo_sdi", "inviata_il", "esito_il"]
    company_field = "azienda"
    list_group_by = ["stato", "canale", "inviata_il:mese"]
    buttons = ["scarica"]

    def col_cliente(self, obj):
        return obj.fattura.cliente
    col_cliente.short_description = "Cliente"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("fattura__cliente")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def scarica(self, request, obj):
        return redirect(reverse("sdi:xml", args=[obj.pk]))
    scarica.short_description = "Scarica l'XML"
    scarica.permission = "view"


@register
class NotificaSdiView(ModelView):
    model = NotificaSdi
    slug = "notifiche"
    list_display = ["nome_file", "tipo", "trasmissione", "identificativo_sdi", "ricevuta_il"]
    list_filter = ["tipo", "ricevuta_il"]
    search_fields = ["nome_file", "identificativo_sdi", "file_fattura"]
    form_layout = [("Notifica", [("tipo", "nome_file"), ("trasmissione", "identificativo_sdi"), "ricevuta_il"])]
    readonly_fields = ["tipo", "nome_file", "trasmissione", "identificativo_sdi", "ricevuta_il"]

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("trasmissione")
        azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
        return qs.filter(azienda_id=azienda_id) if azienda_id is not None else qs

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
