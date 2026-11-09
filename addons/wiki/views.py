from django.core.exceptions import PermissionDenied

from core.viste import Inline, ModelView, register

from . import servizi
from .models import MembroWiki, PaginaWiki, SpazioWiki


@register
class SpazioWikiView(ModelView):
    model = SpazioWiki
    slug = "spazi"
    company_field = "azienda"
    list_display = ["nome", "aperto"]
    form_layout = [("Spazio", ["nome", "descrizione", "aperto"])]
    inlines = [Inline(MembroWiki, "spazio", ["utente", "ruolo"], titolo="Membri", extra=1)]
    ai_descrizione = "Gli spazi della wiki interna con i loro membri."

    def get_queryset(self, request):
        return servizi.spazi_leggibili(request.user, request.azienda) if getattr(request, "azienda", None) else SpazioWiki.objects.none()

    def has_add_permission(self, request):
        return super().has_add_permission(request) and servizi.gestore(request.user)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and servizi.gestore(request.user)


@register
class PaginaWikiView(ModelView):
    """Le pagine della wiki: si leggono negli spazi aperti o di cui si è membri, si scrivono se si è membri che scrivono."""
    model = PaginaWiki
    slug = "pagine"
    company_field = "azienda"
    list_display = ["titolo", "spazio", "padre", "aggiornata_il", "aggiornata_da"]
    list_filter = ["spazio"]
    search_fields = ["titolo", "testo"]
    form_layout = [("Pagina", [("titolo", "spazio"), ("padre", "ordine"), "testo"])]
    chatter = True
    ai_descrizione = "Le pagine della wiki interna: procedure, guide e conoscenza dell'azienda, in markdown."

    def get_queryset(self, request):
        if not getattr(request, "azienda", None):
            return PaginaWiki.objects.none()
        return super().get_queryset(request).filter(spazio__in=servizi.spazi_leggibili(request.user, request.azienda))

    def layout_dettaglio(self):
        return [("Pagina", [["spazio", "padre"], ["aggiornata_il", "aggiornata_da"]])]

    def get_form_class(self, request=None):
        classe = super().get_form_class(request)

        class Form(classe):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if request is not None and "spazio" in self.fields:
                    scrivibili = [s.pk for s in servizi.spazi_leggibili(request.user, request.azienda) if servizi.puo_scrivere(request.user, s)]
                    self.fields["spazio"].queryset = self.fields["spazio"].queryset.filter(pk__in=scrivibili)
                if "padre" in self.fields:
                    self.fields["padre"].queryset = self.fields["padre"].queryset.filter(spazio__in=servizi.spazi_leggibili(request.user, request.azienda)) \
                        if request is not None else self.fields["padre"].queryset
        return Form

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or servizi.puo_scrivere(request.user, obj.spazio))

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or servizi.puo_scrivere(request.user, obj.spazio))

    def save_model(self, request, obj, form, change):
        if not servizi.puo_scrivere(request.user, obj.spazio):
            raise PermissionDenied
        obj.aggiornata_da = request.user
        super().save_model(request, obj, form, change)
        servizi.salva_versione(obj, request.user)
