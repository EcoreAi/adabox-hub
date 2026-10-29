from django.db.models import Q

from core import chatter
from core.viste import ModelView, register

from .models import (Compito, FaseCompito, Milestone, Progetto, Rilascio, Sprint, TipoCompito, blocco, crea_ciclo,
                     progetti_visibili)


class DelProgettoVisibile(ModelView):
    """Viste di oggetti di un progetto: si vedono e si scelgono solo quelli dei progetti visibili."""
    campi_progetto = ("progetto",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser or request.user.has_perm("progetti.vedi_tutti_progetti"):
            return qs
        return qs.filter(progetto__in=progetti_visibili(request.user).values("pk"))

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None:
            return base
        progetti = progetti_visibili(request.user)

        def __init__(form, *args, **kwargs):
            base.__init__(form, *args, **kwargs)
            if "progetto" in form.fields:
                form.fields["progetto"].queryset = form.fields["progetto"].queryset.filter(pk__in=progetti.values("pk"))
        return type(base)(base.__name__, (base,), {"__init__": __init__, "__module__": base.__module__})


@register
class ProgettoView(ModelView):
    model = Progetto
    slug = "progetti"
    list_display = ["nome", "codice", "cliente", "responsabile", "stato", "fine"]
    list_filter = ["stato", "responsabile", "cliente"]
    search_fields = ["nome", "codice", "descrizione"]
    form_layout = [
        ("Progetto", ["nome", ("cliente", "responsabile"), ("inizio", "fine"), ("stato", "budget_ore"), "membri",
                      "descrizione", "@proprieta"]),
    ]
    readonly_fields = ["codice"]
    company_field = "azienda"
    sequence_field = ("codice", "progetti.progetto")
    kanban_group = "stato"
    kanban_fields = ["codice", "cliente", "responsabile", "fine"]
    list_group_by = ["stato", "responsabile", "cliente"]
    chatter = True
    tracked_fields = ["stato", "responsabile", "fine", "budget_ore"]
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
    list_display = ["titolo", "tipo", "progetto", "fase", "sprint", "scadenza", "priorita", "punti", "ore_previste"]
    list_filter = ["progetto", "tipo", "fase", "sprint", "milestone", "rilascio", "assegnatari", "priorita", "scadenza"]
    search_fields = ["titolo", "descrizione", "progetto__nome"]
    form_layout = [
        ("Compito", ["titolo", ("progetto", "tipo"), ("fase", "priorita"), ("scadenza", "ore_previste"),
                     "assegnatari", "descrizione", "@proprieta"]),
        ("Pianificazione", [("sprint", "punti"), ("milestone", "rilascio"), ("padre", "bloccato_da")]),
    ]
    readonly_fields = ["creato", "completato_il"]
    company_field = "azienda"
    list_group_by = ["progetto", "tipo", "fase", "sprint", "milestone", "rilascio", "assegnatari", "scadenza:mese"]
    list_sum = ["ore_previste", "punti"]
    kanban_group = "fase"
    kanban_fields = ["tipo", "progetto", "scadenza", "priorita", "punti"]
    calendar_date = "scadenza"
    calendar_color = "priorita"
    graph = {"tipi": ["barre", "torta"], "misure": ["count", "sum:ore_previste", "sum:punti"],
             "per": ["fase", "tipo", "progetto", "sprint", "priorita"]}
    chatter = True
    tracked_fields = ["fase", "scadenza", "priorita", "sprint", "rilascio", "milestone"]
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
            for campo in ("padre", "bloccato_da", "milestone", "sprint", "rilascio"):
                if campo in form.fields:
                    form.fields[campo].queryset = form.fields[campo].queryset.filter(
                        progetto__in=progetti.values("pk"))
            if "bloccato_da" in form.fields and form.instance.pk:
                form.fields["bloccato_da"].queryset = form.fields["bloccato_da"].queryset.exclude(pk=form.instance.pk)

        def clean(form):
            dati = base.clean(form)
            bloccanti = dati.get("bloccato_da")
            if bloccanti is None:
                return dati
            compito = form.instance
            if compito.pk and crea_ciclo(compito, bloccanti):
                form.add_error("bloccato_da", "Dipendenza circolare: uno di questi compiti aspetta già questo.")
            elif dati.get("progetto") and any(b.progetto_id != dati["progetto"].pk for b in bloccanti):
                form.add_error("bloccato_da", "I compiti bloccanti devono essere dello stesso progetto.")
            fase = dati.get("fase")
            aperti = [b for b in bloccanti if not b.fase.chiusa]
            if fase is not None and fase.chiusa and aperti:
                form.add_error("fase", blocco(aperti))
            return dati
        return type(base)(base.__name__, (base,), {"__init__": __init__, "clean": clean, "__module__": base.__module__})

    def kanban_vietato(self, request, obj):
        if obj.fase.chiusa and (aperti := obj.bloccanti_aperti()):
            return blocco(aperti)
        return None

    def completa(self, request, obj):
        fase = FaseCompito.objects.filter(chiusa=True).first()
        if fase is None:
            return "Nessuna fase di completamento configurata."
        if aperti := obj.bloccanti_aperti():
            return blocco(aperti)
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


@register
class TipoCompitoView(ModelView):
    model = TipoCompito
    slug = "tipi"
    list_display = ["nome", "colore", "ordine", "difetto"]


@register
class MilestoneView(DelProgettoVisibile):
    model = Milestone
    slug = "milestone"
    list_display = ["nome", "progetto", "scadenza"]
    list_filter = ["progetto", "scadenza"]
    search_fields = ["nome", "progetto__nome"]
    form_layout = [("Milestone", [("nome", "progetto"), "scadenza", "descrizione"])]
    company_field = "azienda"
    calendar_date = "scadenza"
    chatter = True


@register
class SprintView(DelProgettoVisibile):
    model = Sprint
    slug = "sprint"
    list_display = ["nome", "progetto", "inizio", "fine", "stato"]
    list_filter = ["progetto", "stato"]
    search_fields = ["nome", "progetto__nome", "obiettivo"]
    form_layout = [("Sprint", [("nome", "progetto"), ("inizio", "fine"), "stato", "obiettivo"])]
    company_field = "azienda"
    kanban_group = "stato"
    kanban_fields = ["progetto", "inizio", "fine"]
    chatter = True
    tracked_fields = ["stato", "fine"]
    buttons = ["avvia", "chiudi"]

    def get_buttons(self, request, obj):
        ammessi = {Sprint.PIANIFICATO: {"avvia"}, Sprint.ATTIVO: {"chiudi"}}.get(obj.stato, set())
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in ammessi]

    def avvia(self, request, obj):
        if obj.stato != Sprint.PIANIFICATO:
            return "Lo sprint non è pianificato."
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.stato = Sprint.ATTIVO
        obj.save(update_fields=["stato"])
        chatter.traccia(obj, vecchi, request.user)
        return f"Sprint «{obj.nome}» avviato."
    avvia.short_description = "Avvia lo sprint"

    def chiudi(self, request, obj):
        """Chiude lo sprint: i compiti non completati passano allo sprint pianificato successivo (o a nessuno)."""
        if obj.stato != Sprint.ATTIVO:
            return "Lo sprint non è in corso."
        prossimo = obj.successivo()
        aperti = obj.compiti.filter(fase__chiusa=False)
        n = aperti.update(sprint=prossimo)
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.stato = Sprint.CHIUSO
        obj.save(update_fields=["stato"])
        chatter.traccia(obj, vecchi, request.user)
        totali, fatti = obj.punti()
        dove = f"in «{prossimo.nome}»" if prossimo else "nel backlog del progetto"
        chatter.scrivi(obj, request.user, f"Sprint chiuso: {fatti} punti completati su {totali}; "
                                          f"{n} compiti aperti spostati {dove}.", tipo="nota")
        return f"Sprint chiuso: {n} compiti aperti spostati {dove}."
    chiudi.short_description = "Chiudi lo sprint"


@register
class RilascioView(DelProgettoVisibile):
    model = Rilascio
    slug = "rilasci"
    list_display = ["versione", "progetto", "data_prevista", "stato", "rilasciato_il"]
    list_filter = ["progetto", "stato"]
    search_fields = ["versione", "progetto__nome", "note"]
    form_layout = [("Rilascio", [("progetto", "versione"), "data_prevista", "note"])]
    readonly_fields = ["stato", "rilasciato_il"]
    company_field = "azienda"
    calendar_date = "data_prevista"
    chatter = True
    tracked_fields = ["stato", "data_prevista"]
    buttons = ["rilascia"]

    def get_buttons(self, request, obj):
        if obj.stato == Rilascio.RILASCIATO:
            return []
        return super().get_buttons(request, obj)

    def rilascia(self, request, obj):
        vecchi = chatter.valori(obj, self.tracked_fields)
        if not obj.rilascia(request.user):
            return "Il rilascio è già pubblicato."
        chatter.traccia(obj, vecchi, request.user)
        return f"Versione {obj.versione} rilasciata."
    rilascia.short_description = "Rilascia"
