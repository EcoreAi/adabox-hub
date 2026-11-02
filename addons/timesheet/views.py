from django.utils import timezone
from django.utils.html import format_html

from core.viste import ModelView, register
from progetti.models import Compito, progetti_visibili

from .models import RigaOre


def vede_tutte(user):
    return user.is_superuser or user.has_perm("timesheet.vedi_tutte_ore")


@register
class RigaOreView(ModelView):
    model = RigaOre
    slug = "ore"
    list_display = ["data", "utente", "progetto", "compito", "descrizione", "ore", "fatturabile", "stato"]
    list_filter = ["progetto", "utente", "fatturabile", "approvata", "bloccata", "data"]
    search_fields = ["descrizione", "progetto__nome", "compito__titolo"]
    form_layout = [("Ore", [("data", "ore"), ("progetto", "compito"), "descrizione", ("utente", "fatturabile")])]
    company_field = "azienda"
    list_group_by = ["progetto", "utente", "compito", "data:mese"]
    list_sum = ["ore"]
    calendar_date = "data"
    graph = {"tipi": ["barre", "torta", "linee"], "misure": ["sum:ore", "count"],
             "per": ["progetto", "utente", "data:mese"]}
    export_fields = ["data", "utente", "progetto", "compito", "descrizione", "ore", "fatturabile"]
    actions = ["approva", "riapri"]
    api = True

    def col_stato(self, obj):
        if obj.bloccata:
            return format_html('<span class="ui-pill ui-pill-info">Fatturata</span>')
        if obj.approvata:
            return format_html('<span class="ui-pill ui-pill-ok">Approvata</span>')
        return format_html('<span class="ui-pill ui-pill-neutral">Da approvare</span>')
    col_stato.short_description = "Stato"

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.modificabile)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or obj.modificabile)

    def approva(self, request, queryset):
        n = queryset.filter(approvata=False).update(approvata=True, approvata_da=request.user, approvata_il=timezone.now())
        return f"Ore approvate: {n} righe."
    approva.short_description = "Approva"
    approva.permission = "timesheet.approva_ore"

    def riapri(self, request, queryset):
        n = queryset.filter(approvata=True, bloccata=False).update(approvata=False, approvata_da=None, approvata_il=None)
        return f"Ore riaperte: {n} righe."
    riapri.short_description = "Riapri"
    riapri.permission = "timesheet.approva_ore"

    def get_queryset(self, request):
        """Chi non ha timesheet.vedi_tutte_ore vede solo le proprie ore (e solo dei progetti che vede)."""
        qs = super().get_queryset(request)
        user = request.user
        if vede_tutte(user):
            return qs
        return qs.filter(utente=user, progetto__in=progetti_visibili(user).values("pk"))

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None:
            return base
        user = request.user
        progetti = progetti_visibili(user).filter(stato="attivo").values("pk")

        def __init__(form, *args, **kwargs):
            base.__init__(form, *args, **kwargs)
            if "progetto" in form.fields:
                form.fields["progetto"].queryset = form.fields["progetto"].queryset.filter(pk__in=progetti)
            if "compito" in form.fields:
                form.fields["compito"].queryset = Compito.objects.filter(progetto__in=progetti)
            if not vede_tutte(user):
                form.fields.pop("utente", None)            # si registra solo per sé
        return type(base)(base.__name__, (base,), {"__init__": __init__, "__module__": base.__module__})

    def save_model(self, request, obj, form, change):
        if obj.utente_id is None:
            obj.utente = request.user
        super().save_model(request, obj, form, change)
