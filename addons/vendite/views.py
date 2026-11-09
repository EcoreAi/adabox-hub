from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from core import chatter, lavori
from core.models import Messaggio
from core.viste import Inline, ModelView, register, schede

from .models import OrdineVendita, RigaVendita
from . import fido, operazioni
from .segnali import ordine_annullato


def euro(valore):
    from core.viste.gruppi import numero
    return f"{numero(valore)} €"


@register
class OrdineView(ModelView):
    model = OrdineVendita
    slug = "ordini"
    list_display = ["documento", "cliente", "data", "stato", "totale", "commerciale"]
    list_filter = ["stato", "cliente", "commerciale", "data"]
    search_fields = ["numero", "numero_ordine", "cliente__nome", "riferimento_cliente"]
    form_layout = [
        ("Documento", [("cliente", "commerciale"), ("data", "validita"), ("listino", "termine_pagamento"),
                       ("riferimento_cliente", "indirizzo_consegna")]),
        ("Note", ["note", "@proprieta"]),
    ]
    readonly_fields = ["numero", "numero_ordine", "stato", "confermato_il"]
    company_field = "azienda"
    sequence_field = ("numero", "vendite.preventivo")
    inlines = [Inline(RigaVendita, "ordine", ["prodotto", "descrizione", "quantita", "unita", "prezzo", "sconto", "aliquota"],
                      titolo="Righe", extra=2)]
    list_group_by = ["stato", "cliente", "commerciale", "data:mese"]
    list_sum = ["totale"]
    kanban_group = "stato"
    kanban_fields = ["cliente", "totale", "data"]
    kanban_ricco = True
    kanban_colori = {"bozza": "grigio", "inviato": "azzurro", "confermato": "verde", "annullato": "grigio"}
    graph = {"tipi": ["barre", "linee", "torta"], "misure": ["sum:totale", "count"],
             "per": ["data:mese", "commerciale", "cliente", "stato"]}
    chatter = True
    tracked_fields = ["stato", "cliente", "totale", "commerciale"]
    buttons = ["invia", "conferma", "annulla", "riporta_in_bozza"]
    reports = [{"nome": "Stampa", "template": "vendite/report/ordine.html",
                "colonne": [("quantita", "Quantità"), ("prezzo", "Prezzo unitario"), ("sconto", "Sconto"), ("iva", "IVA"), ("importo", "Importo di riga")]}]
    api = True


    def kanban_queryset(self, qs):
        return qs.select_related("cliente", "commerciale")

    def kanban_scheda(self, request, obj):
        esito = {OrdineVendita.CONFERMATO: (*schede.FATTO, f"Confermato il {obj.confermato_il:%d/%m/%Y}" if obj.confermato_il else "Confermato"),
                 OrdineVendita.ANNULLATO: (*schede.FERMO, "Annullato")}.get(obj.stato) or schede.entro(obj.validita, "Valido fino al", "Scaduto il", "Senza scadenza")
        etichette = {OrdineVendita.ACCETTATO: [("Accettato online", "verde")], OrdineVendita.RIFIUTATO: [("Rifiutato online", "rosa")]}.get(obj.risposta)
        return schede.scheda(esito, sottotitolo=obj.cliente.nome, valore=schede.euro(obj.totale), etichette=etichette, persona=schede.persona(obj.commerciale))

    def kanban_colonna(self, request, valore, qs):
        return {"riepilogo": schede.euro_tondi(qs.aggregate(t=Sum("totale"))["t"])}

    def col_documento(self, obj):
        return str(obj)
    col_documento.short_description = "Documento"

    def col_totale(self, obj):
        return euro(obj.totale)
    col_totale.short_description = "Totale"

    def has_change_permission(self, request, obj=None):
        """Un ordine confermato o annullato non si modifica più (si riporta in bozza se annullato)."""
        return super().has_change_permission(request, obj) and (obj is None or obj.modificabile)

    def save_model(self, request, obj, form, change):
        if not change and obj.commerciale_id is None:
            obj.commerciale = request.user
        super().save_model(request, obj, form, change)

    def dopo_righe(self, request, obj):
        obj.ricalcola()

    def totali(self, obj):
        voci = [("Imponibile", euro(obj.imponibile))]
        voci += [(f"IVA {g['aliquota']}", euro(g["imposta"])) for g in obj.riepilogo_iva()]
        return voci + [("Totale", euro(obj.totale))]

    def get_buttons(self, request, obj):
        """Solo i bottoni che hanno senso nello stato del documento."""
        ammessi = {OrdineVendita.BOZZA: {"invia", "conferma", "annulla"},
                   OrdineVendita.INVIATO: {"invia", "conferma", "annulla", "riporta_in_bozza"},
                   OrdineVendita.CONFERMATO: {"annulla"},
                   OrdineVendita.ANNULLATO: {"riporta_in_bozza"}}[obj.stato]
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in ammessi]

    def _stato(self, request, obj, stato, **altri):
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.stato = stato
        for campo, valore in altri.items():
            setattr(obj, campo, valore)
        obj.save(update_fields=["stato", *altri])
        chatter.traccia(obj, vecchi, request.user)

    def invia(self, request, obj):
        if obj.stato == OrdineVendita.ANNULLATO:
            return "Un documento annullato non si invia."
        if not obj.cliente.email:
            return f"Il cliente {obj.cliente} non ha un indirizzo email."
        if not obj.righe.exists():
            return "Il documento non ha righe."
        if obj.stato == OrdineVendita.BOZZA:
            self._stato(request, obj, OrdineVendita.INVIATO)
        if obj.risposta == OrdineVendita.RIFIUTATO:      # un nuovo invio riapre la risposta
            obj.risposta, obj.risposta_il, obj.risposta_ip, obj.risposta_motivo = "", None, None, ""
            obj.save(update_fields=["risposta", "risposta_il", "risposta_ip", "risposta_motivo"])
        lavori.accoda("vendite.lavori.invia", ordine_id=obj.pk, utente_id=request.user.pk)
        return f"{obj.titolo_documento} {obj} inviato a {obj.cliente.email}."
    invia.short_description = "Invia per email"
    invia.rischio = "irreversibile"

    def conferma(self, request, obj):
        if not obj.modificabile:
            return f"{obj} non è un preventivo da confermare."
        if not obj.righe.exists():
            return "Il documento non ha righe."
        esito = fido.controllo(obj)
        if esito and esito["blocca"]:
            return f"Ordine non confermato. {esito['testo']}"
        operazioni.conferma(obj, request.user)
        if esito:
            chatter.scrivi(obj, request.user, f"Confermato oltre il fido. {esito['testo']}", tipo=Messaggio.NOTA)
            return f"Ordine {obj.numero_ordine} confermato. Attenzione: {esito['testo']}"
        return f"Ordine {obj.numero_ordine} confermato."
    conferma.short_description = "Conferma l'ordine"
    conferma.rischio = "irreversibile"

    def annulla(self, request, obj):
        if obj.stato == OrdineVendita.ANNULLATO:
            return f"{obj} è già annullato."
        stato = obj.stato
        try:
            with transaction.atomic():
                self._stato(request, obj, OrdineVendita.ANNULLATO)
                risposte = ordine_annullato.send(sender=OrdineVendita, ordine=obj, utente=request.user)
        except ValidationError as e:
            obj.stato = stato
            return " ".join(e.messages)
        return " ".join([f"{obj} annullato.", *(testo for _, testo in risposte if testo)])
    annulla.short_description = "Annulla"

    def riporta_in_bozza(self, request, obj):
        if obj.stato not in (OrdineVendita.INVIATO, OrdineVendita.ANNULLATO) or obj.numero_ordine:
            return "Solo un preventivo inviato o annullato (mai confermato) torna in bozza."
        self._stato(request, obj, OrdineVendita.BOZZA)
        return f"{obj} riportato in bozza."
    riporta_in_bozza.short_description = "Riporta in bozza"
