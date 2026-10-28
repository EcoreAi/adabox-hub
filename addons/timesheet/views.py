from core.viste import ModelView, register
from progetti.models import Compito, progetti_visibili

from .models import RigaOre


def vede_tutte(user):
    return user.is_superuser or user.has_perm("timesheet.vedi_tutte_ore")


@register
class RigaOreView(ModelView):
    model = RigaOre
    slug = "ore"
    list_display = ["data", "utente", "progetto", "compito", "descrizione", "ore", "fatturabile"]
    list_filter = ["progetto", "utente", "fatturabile", "data"]
    search_fields = ["descrizione", "progetto__nome", "compito__titolo"]
    form_layout = [("Ore", [("data", "ore"), ("progetto", "compito"), "descrizione", ("utente", "fatturabile")])]
    company_field = "azienda"
    list_group_by = ["progetto", "utente", "compito", "data:mese"]
    list_sum = ["ore"]
    calendar_date = "data"
    graph = {"tipi": ["barre", "torta", "linee"], "misure": ["sum:ore", "count"],
             "per": ["progetto", "utente", "data:mese"]}
    export_fields = ["data", "utente", "progetto", "compito", "descrizione", "ore", "fatturabile"]
    api = True

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
