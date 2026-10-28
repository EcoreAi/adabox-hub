from django.shortcuts import redirect
from django.template.defaultfilters import filesizeformat
from django.urls import reverse

from core.viste import ModelView, register

from . import accesso, servizi
from .models import Cartella, Documento, Tag


@register
class CartellaView(ModelView):
    model = Cartella
    slug = "cartelle"
    list_display = ["__str__", "modello"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Cartella", [("nome", "padre"), "descrizione"]),
                   ("Permessi", [("gruppi_lettura", "gruppi_scrittura")]),
                   ("Allegati dei record", ["modello"])]
    company_field = "azienda"

    def col___str__(self, obj):
        return obj.percorso()
    col___str__.short_description = "Cartella"


@register
class TagView(ModelView):
    model = Tag
    slug = "tag"
    list_display = ["nome", "colore"]
    search_fields = ["nome"]
    form_layout = [("Tag", [("nome", "colore")])]


@register
class DocumentoView(ModelView):
    model = Documento
    slug = "documenti"
    list_display = ["nome", "cartella", "proprietario", "dimensione", "creato"]
    list_filter = ["cartella", "tag", "proprietario", "creato"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Documento", [("nome", "cartella"), "tag", "descrizione"]), ("Altro", ["@proprieta"])]
    readonly_fields = ["mime", "dimensione", "proprietario", "bloccato_da", "creato", "modificato"]
    company_field = "azienda"
    list_group_by = ["cartella", "proprietario", "creato:mese"]
    chatter = True
    tracked_fields = ["nome", "cartella"]
    buttons = ["scarica", "blocca", "sblocca", "cestina"]

    def col_dimensione(self, obj):
        return filesizeformat(obj.dimensione)
    col_dimensione.short_description = "Dimensione"

    def get_queryset(self, request):
        qs = super().get_queryset(request).filter(cestinato_il__isnull=True).select_related("cartella", "proprietario")
        if accesso.gestore(request.user):
            return qs
        return qs.filter(cartella__in=[c.pk for c in accesso.visibili(request.user, request.azienda)])

    def has_add_permission(self, request):
        return False                                  # si carica dall'archivio

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or accesso.puo_modificare(request.user, obj))

    def has_delete_permission(self, request, obj=None):
        return False                                  # si passa dal cestino

    def get_buttons(self, request, obj):
        nascosti = {"blocca"} if obj.bloccato_da_id else {"sblocca"}
        if not accesso.puo_modificare(request.user, obj):
            nascosti |= {"blocca", "sblocca", "cestina"}
        return [(n, e) for n, e in super().get_buttons(request, obj) if n not in nascosti]

    def scarica(self, request, obj):
        return redirect(reverse("documenti:scarica", args=[obj.pk]))
    scarica.short_description = "Scarica"
    scarica.permission = "view"

    def blocca(self, request, obj):
        obj.bloccato_da = request.user
        obj.save(update_fields=["bloccato_da"])
        return f"«{obj}» bloccato: solo tu puoi modificarlo."
    blocca.short_description = "Blocca"

    def sblocca(self, request, obj):
        obj.bloccato_da = None
        obj.save(update_fields=["bloccato_da"])
        return f"«{obj}» sbloccato."
    sblocca.short_description = "Sblocca"

    def cestina(self, request, obj):
        servizi.cestina([obj])
        from django.contrib import messages
        messages.success(request, f"«{obj}» spostato nel cestino.")
        return redirect(f"{reverse('documenti:archivio')}?cartella={obj.cartella_id}")
    cestina.short_description = "Sposta nel cestino"
