from django.db.models import Q

from core import chatter
from core.viste import ModelView, register

from .models import Compito, FaseCompito, Progetto, progetti_visibili


@register
class ProgettoView(ModelView):
    model = Progetto
    slug = "progetti"
    list_display = ["nome", "codice", "cliente", "responsabile", "stato", "fine"]
    list_filter = ["stato", "responsabile", "cliente"]
    search_fields = ["nome", "codice", "descrizione"]
    form_layout = [
        ("Progetto", ["nome", ("cliente", "responsabile"), ("inizio", "fine"), "stato", "membri", "descrizione",
                      "@proprieta"]),
    ]
    readonly_fields = ["codice"]
    company_field = "azienda"
    sequence_field = ("codice", "progetti.progetto")
    kanban_group = "stato"
    kanban_fields = ["codice", "cliente", "responsabile", "fine"]
    list_group_by = ["stato", "responsabile", "cliente"]
    chatter = True
    tracked_fields = ["stato", "responsabile", "fine"]
    api = True

    def get_queryset(self, request):
        return progetti_visibili(request.user, super().get_queryset(request))

    def save_model(self, request, obj, form, change):
        if not change and obj.responsabile_id is None:
            obj.responsabile = request.user
        super().save_model(request, obj, form, change)


@register
class CompitoView(ModelView):
    model = Compito
    slug = "compiti"
    list_display = ["titolo", "progetto", "fase", "scadenza", "priorita", "ore_previste"]
    list_filter = ["progetto", "fase", "assegnatari", "priorita", "scadenza"]
    search_fields = ["titolo", "descrizione", "progetto__nome"]
    form_layout = [
        ("Compito", ["titolo", ("progetto", "padre"), ("fase", "priorita"), ("scadenza", "ore_previste"),
                     "assegnatari", "descrizione", "@proprieta"]),
    ]
    readonly_fields = ["creato"]
    company_field = "azienda"
    list_group_by = ["progetto", "fase", "assegnatari", "scadenza:mese"]
    list_sum = ["ore_previste"]
    kanban_group = "fase"
    kanban_fields = ["progetto", "scadenza", "priorita"]
    calendar_date = "scadenza"
    calendar_color = "priorita"
    graph = {"tipi": ["barre", "torta"], "misure": ["count", "sum:ore_previste"], "per": ["fase", "progetto", "priorita"]}
    chatter = True
    tracked_fields = ["fase", "scadenza", "priorita"]
    buttons = ["completa"]
    api = True

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser or user.has_perm("progetti.vedi_tutti_progetti"):
            return qs
        visibili = progetti_visibili(user).values("pk")
        return qs.filter(pk__in=Compito.objects.filter(Q(progetto__in=visibili) | Q(assegnatari=user)).values("pk"))

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None:
            return base
        progetti = progetti_visibili(request.user)

        def __init__(form, *args, **kwargs):
            base.__init__(form, *args, **kwargs)
            if "progetto" in form.fields:
                form.fields["progetto"].queryset = form.fields["progetto"].queryset.filter(pk__in=progetti.values("pk"))
            if "padre" in form.fields:
                form.fields["padre"].queryset = form.fields["padre"].queryset.filter(progetto__in=progetti.values("pk"))
        return type(base)(base.__name__, (base,), {"__init__": __init__, "__module__": base.__module__})

    def completa(self, request, obj):
        fase = FaseCompito.objects.filter(chiusa=True).first()
        if fase is None:
            return "Nessuna fase di completamento configurata."
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.fase = fase
        obj.save(update_fields=["fase"])
        chatter.traccia(obj, vecchi, request.user)
        return f"«{obj}» completato."
    completa.short_description = "Completato"


@register
class FaseCompitoView(ModelView):
    model = FaseCompito
    slug = "fasi"
    list_display = ["nome", "ordine", "chiusa"]
