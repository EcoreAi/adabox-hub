from django.utils import timezone

from core import chatter, lavori, sequenze
from core.viste import Inline, ModelView, register

from .models import OrdineVendita, RigaVendita
from .segnali import ordine_confermato


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
                       "riferimento_cliente"]),
        ("Note", ["note", "@proprieta"]),
    ]
    readonly_fields = ["numero", "numero_ordine", "stato", "confermato_il"]
    company_field = "azienda"
    sequence_field = ("numero", "vendite.preventivo")
    inlines = [Inline(RigaVendita, "ordine", ["prodotto", "descrizione", "quantita", "prezzo", "sconto", "aliquota"],
                      titolo="Righe", extra=2)]
    list_group_by = ["stato", "cliente", "commerciale", "data:mese"]
    list_sum = ["totale"]
    kanban_group = "stato"
    kanban_fields = ["cliente", "totale", "data"]
    graph = {"tipi": ["barre", "linee", "torta"], "misure": ["sum:totale", "count"],
             "per": ["data:mese", "commerciale", "cliente", "stato"]}
    chatter = True
    tracked_fields = ["stato", "cliente", "totale", "commerciale"]
    buttons = ["invia", "conferma", "annulla", "riporta_in_bozza"]
    reports = [{"nome": "Stampa", "template": "vendite/report/ordine.html"}]
    api = True

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
        lavori.accoda("vendite.lavori.invia", ordine_id=obj.pk, utente_id=request.user.pk)
        if obj.stato == OrdineVendita.BOZZA:
            self._stato(request, obj, OrdineVendita.INVIATO)
        return f"{obj.titolo_documento} {obj} inviato a {obj.cliente.email}."
    invia.short_description = "Invia per email"
    invia.rischio = "irreversibile"

    def conferma(self, request, obj):
        if not obj.modificabile:
            return f"{obj} non è un preventivo da confermare."
        if not obj.righe.exists():
            return "Il documento non ha righe."
        self._stato(request, obj, OrdineVendita.CONFERMATO, confermato_il=timezone.localdate(),
                    numero_ordine=sequenze.prossimo("vendite.ordine", obj.azienda))
        ordine_confermato.send(sender=OrdineVendita, ordine=obj, utente=request.user)
        return f"Ordine {obj.numero_ordine} confermato."
    conferma.short_description = "Conferma l'ordine"
    conferma.rischio = "irreversibile"

    def annulla(self, request, obj):
        if obj.stato == OrdineVendita.ANNULLATO:
            return f"{obj} è già annullato."
        self._stato(request, obj, OrdineVendita.ANNULLATO)
        return f"{obj} annullato."
    annulla.short_description = "Annulla"

    def riporta_in_bozza(self, request, obj):
        if obj.stato not in (OrdineVendita.INVIATO, OrdineVendita.ANNULLATO) or obj.numero_ordine:
            return "Solo un preventivo inviato o annullato (mai confermato) torna in bozza."
        self._stato(request, obj, OrdineVendita.BOZZA)
        return f"{obj} riportato in bozza."
    riporta_in_bozza.short_description = "Riporta in bozza"
