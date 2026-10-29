from django.utils import timezone

from core import chatter, lavori
from core.viste import Inline, ModelView, register

from .models import OrdineAcquisto, RigaAcquisto
from .segnali import ordine_acquisto_confermato


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
                               "riferimento_fornitore"]),
                   ("Note", ["note", "@proprieta"])]
    readonly_fields = ["numero", "stato", "confermato_il"]
    company_field = "azienda"
    sequence_field = ("numero", "acquisti.ordine")
    inlines = [Inline(RigaAcquisto, "ordine", ["prodotto", "descrizione", "quantita", "prezzo", "sconto", "aliquota"],
                      titolo="Righe", extra=2)]
    list_group_by = ["stato", "fornitore", "data:mese"]
    list_sum = ["totale"]
    kanban_group = "stato"
    kanban_fields = ["fornitore", "totale", "consegna_prevista"]
    graph = {"tipi": ["barre", "torta"], "misure": ["sum:totale", "count"], "per": ["data:mese", "fornitore", "stato"]}
    chatter = True
    tracked_fields = ["stato", "fornitore", "totale", "consegna_prevista"]
    buttons = ["invia", "conferma", "annulla"]
    reports = [{"nome": "Stampa", "template": "acquisti/report/ordine.html"}]
    api = True

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
        super().save_model(request, obj, form, change)

    def dopo_righe(self, request, obj):
        obj.ricalcola()

    def totali(self, obj):
        voci = [("Imponibile", euro(obj.imponibile))]
        voci += [(f"IVA {g['aliquota']}", euro(g["imposta"])) for g in obj.riepilogo_iva()]
        return voci + [("Totale", euro(obj.totale))]

    def get_buttons(self, request, obj):
        ammessi = {"invia", "conferma", "annulla"} if obj.modificabile else (
            {"annulla"} if obj.stato == OrdineAcquisto.CONFERMATO else set())
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in ammessi]

    def _stato(self, request, obj, stato, **altri):
        vecchi = chatter.valori(obj, self.tracked_fields)
        obj.stato = stato
        for campo, valore in altri.items():
            setattr(obj, campo, valore)
        obj.save(update_fields=["stato", *altri])
        chatter.traccia(obj, vecchi, request.user)

    def invia(self, request, obj):
        if not obj.modificabile:
            return "Solo una richiesta si invia."
        if not obj.fornitore.email:
            return f"Il fornitore {obj.fornitore} non ha un indirizzo email."
        lavori.accoda("acquisti.lavori.invia", ordine_id=obj.pk, utente_id=request.user.pk)
        if obj.stato == OrdineAcquisto.BOZZA:
            self._stato(request, obj, OrdineAcquisto.INVIATO)
        return f"Ordine {obj} inviato a {obj.fornitore.email}."
    invia.short_description = "Invia per email"
    invia.rischio = "irreversibile"

    def conferma(self, request, obj):
        if not obj.modificabile:
            return f"{obj} non è da confermare."
        if not obj.righe.exists():
            return "L'ordine non ha righe."
        self._stato(request, obj, OrdineAcquisto.CONFERMATO, confermato_il=timezone.localdate())
        ordine_acquisto_confermato.send(sender=OrdineAcquisto, ordine=obj, utente=request.user)
        return f"Ordine {obj} confermato."
    conferma.short_description = "Conferma l'ordine"
    conferma.rischio = "irreversibile"

    def annulla(self, request, obj):
        if obj.stato == OrdineAcquisto.ANNULLATO:
            return f"{obj} è già annullato."
        self._stato(request, obj, OrdineAcquisto.ANNULLATO)
        return f"{obj} annullato."
    annulla.short_description = "Annulla"
