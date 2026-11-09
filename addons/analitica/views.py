from core.viste import Inline, ModelView, register

from .models import Asse, Budget, ModelloRipartizione, RigaBudget, RigaModello, Voce


@register
class AsseView(ModelView):
    model = Asse
    slug = "assi"
    company_field = "azienda"
    list_display = ["nome", "ordine"]
    form_layout = [("Asse", [("nome", "ordine")])]
    ai_descrizione = "Gli assi della contabilità analitica (centro di costo, commessa…)."


@register
class VoceView(ModelView):
    model = Voce
    slug = "voci"
    company_field = "azienda"
    list_display = ["asse", "codice", "nome", "attiva"]
    list_filter = ["asse", "attiva"]
    search_fields = ["codice", "nome"]
    form_layout = [("Voce", [("asse", "codice"), "nome", ("progetto_id", "attiva")])]
    ai_descrizione = "Le voci degli assi analitici: i centri di costo, le commesse e simili."

    def get_form_class(self, request=None):
        classe = super().get_form_class(request)
        azienda = getattr(request, "azienda", None)

        class Form(classe):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                from django import forms
                from django.apps import apps
                if apps.is_installed("progetti") and "progetto_id" in self.fields:
                    from progetti.models import Progetto
                    scelte = [("", "—")] + [(p.pk, str(p)) for p in Progetto.objects.filter(azienda=azienda).order_by("nome")]
                    self.fields["progetto_id"] = forms.TypedChoiceField(label="progetto", choices=scelte, required=False, coerce=int,
                                                                        empty_value=None, initial=self.instance.progetto_id)
                elif "progetto_id" in self.fields:
                    del self.fields["progetto_id"]
        return Form


@register
class ModelloView(ModelView):
    model = ModelloRipartizione
    slug = "modelli"
    company_field = "azienda"
    list_display = ["nome"]
    form_layout = [("Modello", ["nome"])]
    inlines = [Inline(RigaModello, "modello", ["voce", "percentuale"], titolo="Ripartizione")]
    ai_descrizione = "I modelli di ripartizione: una riga divisa fra più voci in percentuale."


@register
class BudgetView(ModelView):
    model = Budget
    slug = "budget"
    company_field = "azienda"
    list_display = ["voce", "nome", "dal", "al"]
    list_filter = ["voce"]
    form_layout = [("Budget", [("voce", "nome"), ("dal", "al"), "note"])]
    inlines = [Inline(RigaBudget, "budget", ["categoria", "importo"], titolo="Previsto")]
    ai_descrizione = "I budget per voce analitica e periodo, con ricavi e costi previsti per categoria."
