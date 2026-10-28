from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect

from core import chatter, lavori
from core.viste import Inline, ModelView, register

from . import operazioni
from .models import DatiFiscali, Fattura, RigaFattura, Scadenza


def euro(valore):
    from core.viste.gruppi import numero
    return f"{numero(valore)} €"


@register
class FatturaView(ModelView):
    model = Fattura
    slug = "fatture"
    list_display = ["documento", "cliente", "data", "stato", "totale", "pagata"]
    list_filter = ["tipo", "stato", "pagata", "cliente", "data"]
    search_fields = ["numero", "cliente__nome", "cliente__partita_iva", "causale"]
    form_layout = [
        ("Documento", [("cliente", "tipo"), ("data", "termine_pagamento"), "causale"]),
        ("Note", ["note", "@proprieta"]),
    ]
    readonly_fields = ["numero", "stato", "ordine", "fattura_origine", "emessa_il"]
    company_field = "azienda"
    inlines = [Inline(RigaFattura, "fattura", ["prodotto", "descrizione", "quantita", "prezzo", "sconto", "aliquota"],
                      titolo="Righe", extra=2)]
    list_group_by = ["stato", "tipo", "cliente", "data:mese"]
    list_sum = ["totale"]
    kanban_group = "stato"
    kanban_fields = ["cliente", "totale", "data"]
    graph = {"tipi": ["barre", "linee", "torta"], "misure": ["sum:imponibile", "sum:totale", "count"],
             "per": ["data:mese", "cliente", "tipo", "stato"]}
    chatter = True
    tracked_fields = ["stato", "cliente", "totale", "pagata"]
    buttons = ["emetti", "invia", "nota_di_credito", "annulla"]
    reports = [{"nome": "Stampa", "template": "fatturazione/report/fattura.html"}]
    api = True

    def col_documento(self, obj):
        return str(obj)
    col_documento.short_description = "Documento"

    def col_totale(self, obj):
        return euro(obj.totale * obj.segno)
    col_totale.short_description = "Totale"

    def has_change_permission(self, request, obj=None):
        """Una fattura emessa non si modifica più: si corregge con una nota di credito."""
        return super().has_change_permission(request, obj) and (obj is None or obj.modificabile)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or obj.modificabile)

    def dopo_righe(self, request, obj):
        obj.ricalcola()

    def totali(self, obj):
        voci = [("Imponibile", euro(obj.imponibile))]
        voci += [(f"IVA {g['aliquota']}", euro(g["imposta"])) for g in obj.riepilogo_iva()]
        return voci + [("Totale", euro(obj.totale))]

    def get_buttons(self, request, obj):
        ammessi = {Fattura.BOZZA: {"emetti", "annulla"}, Fattura.EMESSA: {"invia", "nota_di_credito"},
                   Fattura.ANNULLATA: set()}[obj.stato]
        if obj.tipo == Fattura.NOTA_CREDITO:
            ammessi.discard("nota_di_credito")
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in ammessi]

    def emetti(self, request, obj):
        vecchi = chatter.valori(obj, self.tracked_fields)
        try:
            operazioni.emetti(obj)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
            return redirect(self.url("dettaglio", pk=obj.pk))
        chatter.traccia(obj, vecchi, request.user)
        return f"{obj} emessa."
    emetti.short_description = "Emetti"

    def invia(self, request, obj):
        if not obj.cliente.email:
            return f"Il cliente {obj.cliente} non ha un indirizzo email."
        lavori.accoda("fatturazione.lavori.invia", fattura_id=obj.pk, utente_id=request.user.pk)
        return f"{obj} inviata a {obj.cliente.email}."
    invia.short_description = "Invia per email"

    def nota_di_credito(self, request, obj):
        try:
            nota = operazioni.nota_di_credito(obj)
        except ValidationError as e:
            return " ".join(e.messages)
        messages.success(request, f"Nota di credito in bozza per {obj}: correggi le righe ed emettila.")
        return redirect(self.url("dettaglio", pk=nota.pk))
    nota_di_credito.short_description = "Nota di credito"

    def annulla(self, request, obj):
        if obj.stato != Fattura.BOZZA:
            return "Si annulla solo una bozza: una fattura emessa si storna con una nota di credito."
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.stato = Fattura.ANNULLATA
        obj.save(update_fields=["stato"])
        chatter.traccia(obj, vecchi, request.user)
        return f"{obj} annullata."
    annulla.short_description = "Annulla"


@register
class ScadenzaView(ModelView):
    model = Scadenza
    slug = "scadenze"
    list_display = ["fattura", "cliente", "data", "importo", "modalita", "pagata", "pagata_il"]
    list_filter = ["pagata", "data", "fattura__cliente"]
    search_fields = ["fattura__numero", "fattura__cliente__nome"]
    readonly_fields = ["fattura", "importo", "modalita", "pagata", "pagata_il"]
    form_layout = [("Scadenza", [("fattura", "data"), ("importo", "modalita"), ("pagata", "pagata_il")])]
    ordering = ["pagata", "data"]
    list_group_by = ["pagata", "data:mese", "fattura__cliente"]
    list_sum = ["importo"]
    actions = ["incassa_selezionate"]
    buttons = ["incassa"]

    def col_cliente(self, obj):
        return obj.fattura.cliente
    col_cliente.short_description = "Cliente"

    def col_importo(self, obj):
        return euro(obj.importo)
    col_importo.short_description = "Importo"

    def get_queryset(self, request):
        """Le scadenze delle fatture dell'azienda corrente."""
        qs = super().get_queryset(request).select_related("fattura__cliente")
        azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
        return qs.filter(fattura__azienda_id=azienda_id) if azienda_id is not None else qs

    def has_add_permission(self, request):
        return False                                    # le scadenze nascono all'emissione

    def has_delete_permission(self, request, obj=None):
        return False

    def get_buttons(self, request, obj):
        return [] if obj.pagata else super().get_buttons(request, obj)

    def incassa(self, request, obj):
        if obj.pagata:
            return "Scadenza già incassata."
        operazioni.incassa(obj)
        return f"Incassati {euro(obj.importo)} di {obj.fattura}."
    incassa.short_description = "Segna incassata"

    def incassa_selezionate(self, request, queryset):
        scadenze = list(queryset.filter(pagata=False))
        for s in scadenze:
            operazioni.incassa(s)
        return f"Scadenze incassate: {len(scadenze)}."
    incassa_selezionate.short_description = "Segna incassate"


@register
class DatiFiscaliView(ModelView):
    model = DatiFiscali
    slug = "dati"
    list_display = ["azienda", "regime_fiscale", "iban"]
    form_layout = [("Emittente", ["azienda", "regime_fiscale", ("iban", "banca")]),
                   ("Registro delle imprese", [("rea_ufficio", "rea_numero"), ("capitale_sociale", "socio_unico")])]
