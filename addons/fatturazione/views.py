from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import redirect

from core import chatter, lavori
from core import azienda as azienda_corrente
from core.viste import Inline, ModelView, register, schede

from . import fatturapa, operazioni
from .models import CassaPrevidenziale, DatiFiscali, Fattura, Incasso, RigaFattura, RiferimentoDDT, Ritenuta, Scadenza


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
        ("Documento", [("cliente", "tipo"), ("data", "termine_pagamento"), "causale", "bollo_modo"]),
        ("Riferimenti per la PA e autofatture", [("rif_tipo", "rif_numero", "rif_data"), ("cig", "cup", "commessa"),
                                                 ("collegata_numero", "collegata_data")]),
        ("Note", ["note", "@proprieta"]),
    ]
    readonly_fields = ["numero", "stato", "ordine", "fattura_origine", "emessa_il"]
    company_field = "azienda"
    inlines = [Inline(RigaFattura, "fattura", ["prodotto", "descrizione", "quantita", "unita", "prezzo", "sconto", "aliquota"],
                      titolo="Righe", extra=2),
               Inline(CassaPrevidenziale, "fattura", ["tipo", "aliquota_cassa", "aliquota", "soggetta_ritenuta"],
                      titolo="Cassa previdenziale", extra=0),
               Inline(Ritenuta, "fattura", ["tipo", "aliquota_ritenuta", "percentuale_base", "causale"],
                      titolo="Ritenute", extra=0),
               Inline(RiferimentoDDT, "fattura", ["numero", "data"], titolo="DDT (fatture differite)", extra=0)]
    list_group_by = ["stato", "tipo", "cliente", "data:mese"]
    list_sum = ["totale"]
    kanban_group = "stato"
    kanban_fields = ["cliente", "totale", "data"]
    kanban_ricco = True
    kanban_colori = {"bozza": "grigio", "emessa": "azzurro", "annullata": "grigio"}
    graph = {"tipi": ["barre", "linee", "torta"], "misure": ["sum:imponibile", "sum:totale", "count"],
             "per": ["data:mese", "cliente", "tipo", "stato"]}
    chatter = True
    tracked_fields = ["stato", "cliente", "totale", "pagata"]
    buttons = ["emetti", "xml", "invia", "nota_di_credito", "annulla"]
    reports = [{"nome": "Stampa", "template": "fatturazione/report/fattura.html",
                "colonne": [("sconto", "Sconto"), ("iva", "Codice IVA di riga")]}]
    api = True


    def kanban_queryset(self, qs):
        return qs.select_related("cliente").prefetch_related("scadenze")

    def _esito_kanban(self, obj):
        if obj.stato == Fattura.BOZZA:
            return "grigio", "icon-edit", "Da emettere"
        if obj.stato == Fattura.ANNULLATA:
            return (*schede.FERMO, "Annullata")
        if not obj.incassabile:
            return (*schede.FATTO, "Emessa")
        aperte = [s.data for s in obj.scadenze.all() if not s.pagata]
        return schede.entro(min(aperte), "Scade il", "Scaduta il") if aperte else (*schede.FATTO, "Incassata")

    def kanban_scheda(self, request, obj):
        return schede.scheda(self._esito_kanban(obj), sottotitolo=obj.cliente.nome, valore=schede.euro(obj.totale),
                             righe=[f"Del {obj.data:%d/%m/%Y}"], etichette=[(obj.get_tipo_display().split(":")[0], "viola")] if obj.tipo != Fattura.FATTURA else None)

    def kanban_colonna(self, request, valore, qs):
        """Le note di credito tolgono, non aggiungono."""
        fatture = qs.exclude(tipo=Fattura.NOTA_CREDITO).aggregate(t=Sum("totale"))["t"] or 0
        note = qs.filter(tipo=Fattura.NOTA_CREDITO).aggregate(t=Sum("totale"))["t"] or 0
        return {"riepilogo": schede.euro_tondi(fatture - note)}

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
        voci.append(("Totale", euro(obj.totale)))
        if obj.iva_in_scissione:
            voci.append(("IVA versata dal cliente (scissione)", euro(-obj.iva_in_scissione)))
        if obj.ritenute:
            voci.append(("Ritenute", euro(-obj.ritenute)))
        if obj.iva_in_scissione or obj.ritenute:
            voci.append(("Netto a pagare", euro(obj.da_incassare)))
        if obj.bollo:
            voci.append(("Bollo virtuale", euro(obj.bollo)))
        return voci

    def get_buttons(self, request, obj):
        ammessi = {Fattura.BOZZA: {"emetti", "annulla"}, Fattura.EMESSA: {"xml", "invia", "nota_di_credito"},
                   Fattura.ANNULLATA: set()}[obj.stato]
        if obj.tipo not in Fattura.STORNABILI:
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
    emetti.rischio = "irreversibile"

    def xml(self, request, obj):
        try:
            nome, contenuto = fatturapa.genera(obj)
        except ValidationError as e:
            for m in e.messages:
                messages.error(request, m)
            return redirect(self.url("dettaglio", pk=obj.pk))
        risposta = HttpResponse(contenuto, content_type="application/xml")
        risposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        return risposta
    xml.short_description = "Fattura elettronica (XML)"
    xml.ai = False
    xml.permission = "view"

    def invia(self, request, obj):
        if not obj.cliente.email:
            return f"Il cliente {obj.cliente} non ha un indirizzo email."
        lavori.accoda("fatturazione.lavori.invia", fattura_id=obj.pk, utente_id=request.user.pk)
        return f"{obj} inviata a {obj.cliente.email}."
    invia.short_description = "Invia per email"
    invia.rischio = "irreversibile"

    def nota_di_credito(self, request, obj):
        try:
            nota = operazioni.nota_di_credito(obj)
        except ValidationError as e:
            return " ".join(e.messages)
        messages.success(request, f"Nota di credito in bozza per {obj}: correggi le righe ed emettila.")
        return redirect(self.url("dettaglio", pk=nota.pk))
    nota_di_credito.short_description = "Nota di credito"
    nota_di_credito.rischio = "irreversibile"

    def annulla(self, request, obj):
        if obj.stato != Fattura.BOZZA:
            return "Si annulla solo una bozza: una fattura emessa si storna con una nota di credito."
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.stato = Fattura.ANNULLATA
        obj.save(update_fields=["stato"])
        chatter.traccia(obj, vecchi, request.user)
        return f"{obj} annullata."
    annulla.short_description = "Annulla"
    annulla.rischio = "irreversibile"


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
    chatter = True                # solleciti e accordi col cliente restano sulla scadenza
    tracked_fields = ["data", "pagata"]

    def indirizzi_suggeriti(self, obj):
        return super().indirizzi_suggeriti(obj.fattura.cliente) if obj.fattura_id and obj.fattura.cliente_id else []

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
        return qs.filter(fattura__azienda_id=azienda_id) if azienda_id is not None else qs.none()

    def has_add_permission(self, request):
        return False                                    # le scadenze nascono all'emissione

    def has_delete_permission(self, request, obj=None):
        return False

    def get_buttons(self, request, obj):
        return [] if obj.pagata else super().get_buttons(request, obj)

    def incassa(self, request, obj):
        if obj.pagata:
            return "Scadenza già incassata."
        residuo = obj.residuo
        operazioni.incassa(obj)
        return f"Incassati {euro(residuo)} di {obj.fattura}."
    incassa.short_description = "Segna incassata"

    def incassa_selezionate(self, request, queryset):
        scadenze = list(queryset.filter(pagata=False))
        for s in scadenze:
            operazioni.incassa(s)
        return f"Scadenze incassate: {len(scadenze)}."
    incassa_selezionate.short_description = "Segna incassate"


@register
class IncassoView(ModelView):
    """Il registro degli incassi: si creano dalla fattura e si annullano da lì."""
    model = Incasso
    slug = "incassi"
    list_display = ["data", "documento", "cliente", "tipo", "metodo", "importo", "riferimento"]
    list_filter = ["tipo", "metodo", "data"]
    search_fields = ["scadenza__fattura__numero", "scadenza__fattura__cliente__nome", "riferimento"]
    readonly_fields = ["scadenza", "tipo", "data", "importo", "metodo", "riferimento", "nota_credito", "utente"]
    form_layout = [("Incasso", [("scadenza", "tipo"), ("data", "importo"), ("metodo", "riferimento"),
                                ("nota_credito", "utente")])]
    ordering = ["-data", "-pk"]
    list_group_by = ["tipo", "metodo", "data:mese"]
    list_sum = ["importo"]
    graph = {"tipi": ["barre", "linee"], "misure": ["sum:importo", "count"], "per": ["data:mese", "metodo", "tipo"]}

    def col_documento(self, obj):
        return obj.scadenza.fattura
    col_documento.short_description = "Documento"

    def col_cliente(self, obj):
        return obj.scadenza.fattura.cliente
    col_cliente.short_description = "Cliente"

    def col_importo(self, obj):
        return euro(obj.importo)
    col_importo.short_description = "Importo"

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("scadenza__fattura__cliente")
        azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
        return qs.filter(scadenza__fattura__azienda_id=azienda_id) if azienda_id is not None else qs.none()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@register
class DatiFiscaliView(ModelView):
    model = DatiFiscali
    slug = "dati"

    def get_queryset(self, request):
        """Solo le aziende in cui l'utente lavora: qui ci sono IBAN e dati fiscali. Da tutte: serve per il cambio d'azienda."""
        return super().get_queryset(request).filter(azienda__in=azienda_corrente.consentite(request.user))

    list_display = ["azienda", "regime_fiscale", "iban"]
    form_layout = [("Emittente", ["azienda", "regime_fiscale", ("iban", "banca"), "bollo_al_cliente"]),
                   ("Registro delle imprese", [("rea_ufficio", "rea_numero"), ("capitale_sociale", "socio_unico")])]
