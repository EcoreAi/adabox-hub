from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect

from core.viste import Inline, ModelView, register

from . import operazioni
from .models import Canone, RigaCanone


def euro(valore):
    from core.viste.gruppi import numero
    return f"{numero(valore)} €"


@register
class CanoneView(ModelView):
    model = Canone
    slug = "canoni"
    list_display = ["numero", "nome", "cliente", "periodicita", "imponibile", "stato", "prossimo_periodo", "scadenza"]
    list_filter = ["stato", "periodicita", "cliente", "rinnovo_tacito", "adeguamento_istat"]
    search_fields = ["numero", "nome", "cliente__nome"]
    form_layout = [
        ("Contratto", [("nome", "cliente"), ("responsabile", "termine_pagamento")]),
        ("Periodi", [("inizio", "periodicita"), "anticipata", "prossimo_periodo"]),
        ("Durata", [("durata_mesi", "preavviso_giorni"), ("rinnovo_tacito", "adeguamento_istat")]),
        ("Fatture", [("emissione_automatica", "invio_automatico")]),
        ("Note", ["note"]),
    ]
    readonly_fields = ["numero", "stato", "imponibile", "scadenza", "cessa_il", "disdetto_il"]
    company_field = "azienda"
    sequence_field = ("numero", "ricorrenti.contratto")
    inlines = [Inline(RigaCanone, "canone", ["prodotto", "descrizione", "quantita", "prezzo", "sconto", "aliquota"], titolo="Righe", extra=2)]
    list_group_by = ["stato", "cliente", "periodicita"]
    list_sum = ["imponibile"]
    chatter = True
    tracked_fields = ["stato", "nome", "cliente", "periodicita", "scadenza", "imponibile", "prossimo_periodo", "emissione_automatica"]
    buttons = ["attiva", "fattura_ora", "sospendi", "riprendi", "disdici", "revoca_disdetta"]

    def col_imponibile(self, obj):
        return euro(obj.imponibile)
    col_imponibile.short_description = "Importo per periodo"

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or obj.stato == Canone.BOZZA)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato != Canone.CONCLUSO)

    def dopo_righe(self, request, obj):
        obj.ricalcola()

    def totali(self, obj):
        return [("A periodo", euro(obj.imponibile)), ("Al mese", euro(obj.mensile)), ("All'anno", euro(obj.mensile * 12))]

    def get_buttons(self, request, obj):
        ammessi = {Canone.BOZZA: {"attiva"}, Canone.ATTIVO: {"fattura_ora", "sospendi", "disdici"}, Canone.SOSPESO: {"riprendi"},
                   Canone.DISDETTO: {"fattura_ora", "revoca_disdetta"}, Canone.CONCLUSO: set()}[obj.stato]
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in ammessi]

    def _esegui(self, request, obj, funzione, *altri):
        try:
            return funzione(obj, request.user, *altri), None
        except ValidationError as e:
            return None, " ".join(e.messages)

    def attiva(self, request, obj):
        saltati, errore = self._esegui(request, obj, operazioni.attiva)
        if errore:
            return errore
        testo = f"{obj} attivato: si fattura dal periodo del {obj.prossimo_periodo:%d/%m/%Y}."
        if saltati:
            testo += " I periodi precedenti non si fatturano: per farlo riporta indietro «prossimo periodo»."
        return testo
    attiva.short_description = "Attiva"
    attiva.rischio = "irreversibile"

    def fattura_ora(self, request, obj):
        fattura, errore = self._esegui(request, obj, operazioni.fattura_prossimo)
        if errore:
            return errore
        messages.success(request, f"{fattura} creata in bozza: controllala ed emettila.")
        return redirect("fatturazione:fatture_dettaglio", pk=fattura.pk)
    fattura_ora.short_description = "Fattura ora il prossimo periodo"

    def sospendi(self, request, obj):
        return self._esegui(request, obj, operazioni.sospendi)[1] or f"{obj} sospeso."
    sospendi.short_description = "Sospendi"

    def riprendi(self, request, obj):
        errore = self._esegui(request, obj, operazioni.riprendi)[1]
        return errore or f"{obj} ripreso: si fattura dal periodo del {obj.prossimo_periodo:%d/%m/%Y}."
    riprendi.short_description = "Riprendi"

    def disdici(self, request, obj):
        cessa, errore = self._esegui(request, obj, operazioni.disdici)
        return errore or f"Disdetta registrata: {obj} prosegue e si fattura fino al {cessa:%d/%m/%Y}."
    disdici.short_description = "Registra la disdetta di oggi"
    disdici.rischio = "irreversibile"

    def revoca_disdetta(self, request, obj):
        return self._esegui(request, obj, operazioni.revoca_disdetta)[1] or f"Disdetta revocata: {obj} prosegue."
    revoca_disdetta.short_description = "Revoca la disdetta"
