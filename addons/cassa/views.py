from django.shortcuts import redirect

from core.viste import ModelView, register

from .models import Cassa, ChiusuraCassa, MovimentoCassa


@register
class CassaView(ModelView):
    """Le casse in contanti dell'azienda: saldo, movimenti non ancora chiusi, chiusura con il contato."""
    model = Cassa
    slug = "casse"
    company_field = "azienda"
    list_display = ["nome", "saldo", "responsabile", "predefinita", "attiva"]
    list_filter = ["attiva"]
    search_fields = ["nome"]
    form_layout = [("Cassa", [("nome", "responsabile"), ("saldo_iniziale", "dal"), ("predefinita", "attiva")])]
    buttons = ["chiudi"]
    ai_descrizione = "Le casse in contanti dell'azienda (cassa della sede, piccola cassa) con il saldo atteso."

    def col_saldo(self, obj):
        from core.viste.gruppi import numero
        return f"{numero(obj.saldo)} €"
    col_saldo.short_description = "Saldo"

    def chiudi(self, request, obj):
        return redirect("cassa:chiudi", pk=obj.pk)
    chiudi.short_description = "Chiudi la cassa"
    chiudi.permission = "cassa.add_chiusuracassa"
    chiudi.ai = False


@register
class MovimentoCassaView(ModelView):
    """Entrate e uscite in contanti. Dopo la chiusura della cassa un movimento non si modifica né si elimina."""
    model = MovimentoCassa
    slug = "movimenti"
    company_field = "azienda"
    list_display = ["data", "cassa", "causale", "importo", "descrizione", "controparte", "chiusura"]
    list_filter = ["cassa", "causale", "data"]
    search_fields = ["descrizione", "controparte"]
    list_sum = ["importo"]
    form_layout = [("Movimento", [("cassa", "data"), ("causale", "importo"), ("descrizione", "controparte")])]
    readonly_fields = ["incasso", "chiusura", "utente"]
    ai_descrizione = "I movimenti di cassa in contanti: incassi, rimborsi spese, spese, versamenti e prelievi, differenze di chiusura."

    def get_form_class(self, request=None):
        classe = super().get_form_class(request)
        azienda = getattr(request, "azienda", None)

        class Form(classe):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if "cassa" in self.fields:
                    self.fields["cassa"].queryset = Cassa.objects.filter(azienda=azienda, attiva=True)
                    if not self.instance.pk and not self.initial.get("cassa"):
                        from .operazioni import predefinita
                        cassa = predefinita(azienda)
                        self.fields["cassa"].initial = cassa.pk if cassa else None
                if "causale" in self.fields:
                    self.fields["causale"].choices = [c for c in self.fields["causale"].choices if c[0] != MovimentoCassa.DIFFERENZA]
                self.fields["importo"].help_text = "Rimborsi, spese e versamenti escono comunque: basta l'importo"
        return Form

    def save_model(self, request, obj, form, change):
        if not change:
            obj.utente = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        if obj is not None and (obj.chiusura_id or obj.incasso_id or obj.causale == obj.DIFFERENZA):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and (obj.chiusura_id or obj.incasso_id):
            return False
        return super().has_delete_permission(request, obj)


@register
class ChiusuraView(ModelView):
    """Le chiusure di cassa: si fanno dalla cassa; l'ultima si può annullare."""
    model = ChiusuraCassa
    slug = "chiusure"
    company_field = "azienda"
    list_display = ["data", "cassa", "apertura", "entrate", "uscite", "atteso", "contato", "differenza", "utente"]
    list_filter = ["cassa", "data"]
    list_sum = ["differenza"]
    readonly_fields = ["cassa", "data", "apertura", "entrate", "uscite", "atteso", "contato", "differenza", "nota", "utente", "creata"]
    form_layout = [("Chiusura", [("cassa", "data"), ("apertura", "atteso"), ("entrate", "uscite"), ("contato", "differenza"), "nota", ("utente", "creata")])]
    buttons = ["annulla"]
    ai_descrizione = "Le chiusure delle casse in contanti: saldo atteso, contanti contati e differenza."

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False if obj is not None else super().has_change_permission(request, obj)

    def annulla(self, request, obj):
        from django.core.exceptions import ValidationError

        from . import operazioni
        try:
            cassa = obj.cassa
            operazioni.annulla_chiusura(obj)
        except ValidationError as e:
            return " ".join(e.messages)
        from django.contrib import messages
        messages.success(request, "Chiusura annullata: i movimenti sono di nuovo modificabili.")
        return redirect("cassa:casse_dettaglio", pk=cassa.pk)
    annulla.short_description = "Annulla la chiusura"
    annulla.permission = "cassa.delete_chiusuracassa"
    annulla.rischio = "irreversibile"
    annulla.ai = False
