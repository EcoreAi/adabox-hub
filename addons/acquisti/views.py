from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import redirect
from django.urls import reverse

from core.viste import Inline, ModelView, register, schede

from . import operazioni, riscontro
from .models import (CondizioniFornitore, ContrattoQuadro, Gara, OrdineAcquisto, RegolaApprovazione, RegolaRiordino,
                     RigaAcquisto, RigaContratto, RigaGara, VoceListino)


def euro(valore):
    from core.viste.gruppi import numero
    return f"{numero(valore)} €"


@register
class OrdineAcquistoView(ModelView):
    model = OrdineAcquisto
    slug = "ordini"
    list_display = ["documento", "fornitore", "data", "consegna_prevista", "stato", "totale"]
    list_filter = ["stato", "fornitore", "buyer", "data"]
    search_fields = ["numero", "fornitore__nome", "riferimento_fornitore"]
    form_layout = [("Ordine", [("fornitore", "buyer"), ("data", "consegna_prevista"), "termine_pagamento",
                               ("riferimento_fornitore", "contratto")]),
                   ("Triangolazione", ["consegna_a", "indirizzo_consegna"]),
                   ("Note", ["note", "@proprieta"])]
    readonly_fields = ["numero", "stato", "confermato_il"]
    company_field = "azienda"
    sequence_field = ("numero", "acquisti.ordine")
    inlines = [Inline(RigaAcquisto, "ordine", ["prodotto", "descrizione", "quantita", "unita", "prezzo", "sconto", "aliquota"],
                      titolo="Righe", extra=2)]
    list_group_by = ["stato", "fornitore", "data:mese"]
    list_sum = ["totale"]
    kanban_group = "stato"
    kanban_fields = ["fornitore", "totale", "consegna_prevista"]
    kanban_ricco = True
    kanban_colori = {"bozza": "grigio", "inviato": "azzurro", "da_approvare": "viola", "confermato": "verde",
                     "annullato": "grigio"}
    graph = {"tipi": ["barre", "torta"], "misure": ["sum:totale", "count"], "per": ["data:mese", "fornitore", "stato"]}
    chatter = True
    tracked_fields = operazioni.CAMPI_TRACCIATI
    buttons = ["invia", "conferma", "approva", "rifiuta", "ricevi_residuo", "rendi", "spedito", "annulla"]
    reports = [{"nome": "Stampa", "template": "acquisti/report/ordine.html",
                "colonne": [("prezzo", "Prezzo unitario"), ("sconto", "Sconto"), ("iva", "IVA"), ("importo", "Importo di riga")]}]
    api = True


    def kanban_queryset(self, qs):
        return qs.select_related("fornitore", "buyer")

    def kanban_scheda(self, request, obj):
        esito = (*schede.FERMO, "Annullato") if obj.stato == OrdineAcquisto.ANNULLATO else schede.entro(
            obj.consegna_prevista, "Consegna il", "Consegna attesa dal", "Senza data di consegna")
        return schede.scheda(esito, sottotitolo=obj.fornitore.nome, valore=schede.euro(obj.totale), persona=schede.persona(obj.buyer))

    def kanban_colonna(self, request, valore, qs):
        return {"riepilogo": schede.euro_tondi(qs.aggregate(t=Sum("totale"))["t"])}

    def col_documento(self, obj):
        return str(obj)
    col_documento.short_description = "Ordine"

    def col_totale(self, obj):
        return euro(obj.totale)
    col_totale.short_description = "Totale"

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.modificabile)

    def save_model(self, request, obj, form, change):
        if not change and obj.buyer_id is None:
            obj.buyer = request.user
        if not change:
            operazioni.applica_condizioni(obj)
        super().save_model(request, obj, form, change)

    def dopo_righe(self, request, obj):
        obj.ricalcola()

    def totali(self, obj):
        voci = [("Imponibile", euro(obj.imponibile))]
        voci += [(f"IVA {g['aliquota']}", euro(g["imposta"])) for g in obj.riepilogo_iva()]
        return voci + [("Totale", euro(obj.totale))]

    def get_buttons(self, request, obj):
        ammessi = set()
        if obj.modificabile:
            ammessi = {"invia", "conferma", "annulla"}
        elif obj.stato == OrdineAcquisto.DA_APPROVARE:
            ammessi = {"annulla"}
            if operazioni.puo_decidere(request.user, obj):
                ammessi |= {"approva", "rifiuta"}
        elif obj.stato == OrdineAcquisto.CONFERMATO:
            ammessi = {"annulla"}
            if apps.is_installed("magazzino"):
                stato = riscontro.riepilogo(obj)
                ammessi |= {"ricevi_residuo"} if stato["ha_residuo"] and stato["ha_netto"] else set()
                ammessi |= {"rendi"} if stato["ha_netto"] else set()
            if obj.consegna_a_id and not obj.spedito_il:
                ammessi |= {"spedito"}
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in ammessi]

    def spedito(self, request, obj):
        from . import triangolazione
        try:
            triangolazione.segna_spedito(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Segnato: il fornitore ha spedito a {obj.consegna_a}."
    spedito.short_description = "Spedito al cliente"

    def invia(self, request, obj):
        try:
            operazioni.invia(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Ordine {obj} inviato a {obj.fornitore.email}."
    invia.short_description = "Invia per email"
    invia.rischio = "irreversibile"

    def conferma(self, request, obj):
        try:
            confermato = operazioni.conferma(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Ordine {obj} confermato." if confermato else f"Ordine {obj} inviato in approvazione."
    conferma.short_description = "Conferma l'ordine"
    conferma.rischio = "irreversibile"

    def approva(self, request, obj):
        try:
            confermato = operazioni.approva(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Ordine {obj} approvato e confermato." if confermato else f"Approvato: manca ancora un livello per {obj}."
    approva.short_description = "Approva"
    approva.permission = "view"                         # chi decide lo stabilisce la regola, non il permesso di modifica
    approva.rischio = "irreversibile"
    approva.ai = False                                  # una persona, non l'assistente per suo conto

    def rifiuta(self, request, obj):
        try:
            operazioni.rifiuta(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Ordine {obj} rifiutato: torna a chi l'ha preparato. Scrivi il motivo qui sotto."
    rifiuta.short_description = "Rifiuta"
    rifiuta.permission = "view"
    rifiuta.rischio = "irreversibile"
    rifiuta.ai = False

    def ricevi_residuo(self, request, obj):
        try:
            ricevimento = riscontro.crea_residuo(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return redirect(reverse("magazzino:ricevimenti_dettaglio", args=[ricevimento.pk]))
    ricevi_residuo.short_description = "Ricevi ciò che manca"

    def rendi(self, request, obj):
        try:
            reso = riscontro.crea_reso(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return redirect(reverse("magazzino:consegne_dettaglio", args=[reso.pk]))
    rendi.short_description = "Reso al fornitore"

    def annulla(self, request, obj):
        try:
            return operazioni.annulla(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
    annulla.short_description = "Annulla"


@register
class VoceListinoView(ModelView):
    model = VoceListino
    slug = "listini"
    list_display = ["prodotto", "fornitore", "codice_fornitore", "quantita_minima", "prezzo", "giorni_consegna",
                    "valido_al", "preferito"]
    list_filter = ["fornitore", "preferito"]
    search_fields = ["prodotto__nome", "prodotto__codice", "fornitore__nome", "codice_fornitore"]
    form_layout = [("Voce", [("prodotto", "fornitore"), ("codice_fornitore", "preferito")]),
                   ("Prezzo e consegna", [("prezzo", "quantita_minima"), "giorni_consegna", ("valido_dal", "valido_al")])]
    company_field = "azienda"
    api = True


@register
class CondizioniFornitoreView(ModelView):
    model = CondizioniFornitore
    slug = "condizioni"
    list_display = ["fornitore", "termine_pagamento", "aliquota", "giorni_consegna", "iban"]
    search_fields = ["fornitore__nome", "iban"]
    form_layout = [("Condizioni", ["fornitore", ("termine_pagamento", "aliquota"), ("iban", "giorni_consegna"), "note"])]
    company_field = "azienda"
    api = True


@register
class RegolaApprovazioneView(ModelView):
    model = RegolaApprovazione
    slug = "approvazioni"
    list_display = ["nome", "livello", "soglia", "categoria", "attiva"]
    list_filter = ["attiva", "categoria"]
    search_fields = ["nome"]
    form_layout = [("Regola", ["nome", ("livello", "attiva"), ("soglia", "categoria"), "approvatori"])]
    company_field = "azienda"


@register
class RegolaRiordinoView(ModelView):
    model = RegolaRiordino
    slug = "regole-riordino"
    list_display = ["prodotto", "punto_riordino", "scorta_obiettivo", "fornitore", "automatica"]
    list_filter = ["automatica", "fornitore"]
    search_fields = ["prodotto__nome", "prodotto__codice"]
    form_layout = [("Regola", ["prodotto", ("punto_riordino", "scorta_obiettivo"), ("fornitore", "automatica")])]
    company_field = "azienda"
    api = True


@register
class ContrattoQuadroView(ModelView):
    model = ContrattoQuadro
    slug = "contratti"
    list_display = ["documento", "fornitore", "dal", "al", "stato"]
    list_filter = ["stato", "fornitore"]
    search_fields = ["numero", "fornitore__nome", "riferimento_fornitore"]
    form_layout = [("Contratto", ["fornitore", ("dal", "al"), "riferimento_fornitore"]), ("Note", ["note"])]
    readonly_fields = ["numero", "stato"]
    company_field = "azienda"
    inlines = [Inline(RigaContratto, "contratto", ["prodotto", "prezzo", "quantita"], titolo="Righe", extra=2)]
    chatter = True
    tracked_fields = ["stato", "dal", "al"]
    buttons = ["attiva", "richiama", "chiudi"]
    api = True

    def col_documento(self, obj):
        return str(obj)
    col_documento.short_description = "Contratto"

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato == ContrattoQuadro.BOZZA)

    def get_buttons(self, request, obj):
        ammessi = {ContrattoQuadro.BOZZA: {"attiva"}, ContrattoQuadro.ATTIVO: {"richiama", "chiudi"}}.get(obj.stato, set())
        return [(n, e) for n, e in ModelView.get_buttons(self, request, obj) if n in ammessi]

    def attiva(self, request, obj):
        try:
            operazioni.attiva_contratto(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Contratto {obj} attivo."
    attiva.short_description = "Attiva"
    attiva.permission = "acquisti.change_contrattoquadro"

    def richiama(self, request, obj):
        try:
            ordine = operazioni.richiamo(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return redirect(reverse("acquisti:ordini_modifica", args=[ordine.pk]))
    richiama.short_description = "Crea un ordine di richiamo"
    richiama.permission = "acquisti.add_ordineacquisto"

    def chiudi(self, request, obj):
        try:
            operazioni.chiudi_contratto(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Contratto {obj} chiuso."
    chiudi.short_description = "Chiudi"
    chiudi.permission = "acquisti.change_contrattoquadro"
    chiudi.rischio = "irreversibile"


@register
class GaraView(ModelView):
    model = Gara
    slug = "gare"
    list_display = ["documento", "titolo", "scadenza", "stato"]
    list_filter = ["stato"]
    search_fields = ["numero", "titolo", "fornitori__nome"]
    form_layout = [("Gara", ["titolo", "scadenza", "fornitori"]), ("Note", ["note"])]
    readonly_fields = ["numero", "stato", "vincitore"]
    company_field = "azienda"
    inlines = [Inline(RigaGara, "gara", ["prodotto", "descrizione", "quantita"], titolo="Che cosa serve", extra=2)]
    chatter = True
    tracked_fields = ["stato", "scadenza"]
    buttons = ["crea_offerte", "invia_offerte", "annulla_gara"]
    sequence_field = ("numero", "acquisti.gara")

    def col_documento(self, obj):
        return obj.numero or f"Gara {obj.pk}"
    col_documento.short_description = "Numero"

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato == Gara.APERTA)

    def get_buttons(self, request, obj):
        return ModelView.get_buttons(self, request, obj) if obj.stato == Gara.APERTA else []

    def crea_offerte(self, request, obj):
        try:
            creati = operazioni.crea_offerte(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Richieste create: {creati}. Inserisci i prezzi offerti e confrontale qui sotto." if creati else (
            "Tutti i fornitori invitati hanno già una richiesta.")
    crea_offerte.short_description = "Crea le richieste"
    crea_offerte.permission = "acquisti.add_ordineacquisto"

    def invia_offerte(self, request, obj):
        inviate, senza = operazioni.invia_offerte(obj, request.user)
        testo = f"Richieste inviate: {inviate}."
        return testo + (f" Senza email: {', '.join(senza)}." if senza else "")
    invia_offerte.short_description = "Invia le richieste"
    invia_offerte.permission = "acquisti.change_ordineacquisto"
    invia_offerte.rischio = "irreversibile"

    def annulla_gara(self, request, obj):
        try:
            operazioni.annulla_gara(obj, request.user)
        except ValidationError as e:
            return " ".join(e.messages)
        return "Gara annullata con le sue richieste aperte."
    annulla_gara.short_description = "Annulla la gara"
    annulla_gara.rischio = "irreversibile"
