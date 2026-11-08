"""Consensi, richieste degli interessati, finalità e tempi di conservazione."""
from django import forms

from core.viste import ModelView, register

from .models import Consenso, Finalita, RegolaConservazione, RichiestaInteressato


@register
class ConsensoView(ModelView):
    """Il registro dei consensi: ogni riga è una registrazione, la più recente per finalità vale."""
    model = Consenso
    slug = "consensi"
    list_display = ["il", "contatto", "finalita", "dato", "fonte", "registrato_da"]
    list_filter = ["finalita", "dato", "fonte", "il"]
    search_fields = ["contatto__nome", "contatto__email", "note"]
    form_layout = [("Consenso", [("contatto", "finalita"), ("dato", "fonte"), "il", "note"])]
    readonly_fields = ["registrato_da"]
    company_field = "azienda"
    list_group_by = ["finalita", "dato", "il:mese"]
    ai_descrizione = "Il registro dei consensi privacy dei contatti per finalità (newsletter, profilazione…): dati o revocati, quando e come."

    def has_change_permission(self, request, obj=None):
        return False                                       # una prova non si modifica: se cambia, nuova registrazione

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.registrato_da = obj.registrato_da or request.user
        super().save_model(request, obj, form, change)


@register
class RichiestaView(ModelView):
    """Le richieste degli interessati, con la scadenza di 30 giorni."""
    model = RichiestaInteressato
    slug = "richieste"
    list_display = ["ricevuta_il", "richiedente", "tipo", "contatto", "scadenza", "evasa_il"]
    list_filter = ["tipo", "evasa_il", "ricevuta_il"]
    search_fields = ["richiedente", "contatto__nome", "esito"]
    form_layout = [("Richiesta", [("richiedente", "contatto"), ("tipo", "ricevuta_il"), ("scadenza", "evasa_il"), "esito"])]
    readonly_fields = ["scadenza"]
    company_field = "azienda"
    chatter = True
    tracked_fields = ["evasa_il"]
    ai_descrizione = "Le richieste privacy degli interessati (accesso, cancellazione, portabilità…) con scadenza ed esito."


@register
class FinalitaView(ModelView):
    model = Finalita
    slug = "finalita"
    list_display = ["nome", "base_giuridica", "attiva"]
    form_layout = [("Finalità", [("nome", "base_giuridica"), "descrizione", "attiva"])]


class RegolaForm(forms.ModelForm):
    class Meta:
        model = RegolaConservazione
        fields = ["chiave", "giorni", "attiva"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .conservazione import tipi
        scelte = [(k, f"{v['etichetta']}" + (f" (consigliati {v['giorni']} giorni)" if v.get("giorni") else "")) for k, v in tipi().items()]
        self.fields["chiave"] = forms.ChoiceField(label="dati", choices=scelte)


@register
class RegolaConservazioneView(ModelView):
    """Quanto si tengono i dati che i moduli dichiarano cancellabili; il cron di ogni notte applica le regole."""
    model = RegolaConservazione
    slug = "conservazione"
    list_display = ["chiave", "giorni", "attiva", "ultima_esecuzione", "cancellati"]
    form_class = RegolaForm
    form_layout = [("Regola", [("chiave", "giorni"), "attiva"])]
    readonly_fields = ["ultima_esecuzione", "cancellati"]
    api = False

    def col_chiave(self, obj):
        from .conservazione import etichetta
        return etichetta(obj.chiave)
    col_chiave.short_description = "Dati"
