from django.shortcuts import redirect
from django.urls import reverse

from core.viste import Inline, ModelView, register

from . import passive
from .models import FatturaPassiva, NotificaSdi, RigaPassiva, ScadenzaPassiva, Trasmissione


@register
class TrasmissioneView(ModelView):
    model = Trasmissione
    slug = "trasmissioni"
    list_display = ["nome_file", "fattura", "cliente", "stato", "canale", "inviata_il", "identificativo_sdi"]
    list_filter = ["stato", "canale", "inviata_il"]
    search_fields = ["nome_file", "identificativo_sdi", "fattura__numero", "fattura__cliente__nome"]
    form_layout = [("Trasmissione", [("fattura", "nome_file"), ("stato", "canale"), ("identificativo_sdi", "inviata_il"),
                                     "esito_il"])]
    readonly_fields = ["fattura", "nome_file", "stato", "canale", "identificativo_sdi", "inviata_il", "esito_il"]
    company_field = "azienda"
    list_group_by = ["stato", "canale", "inviata_il:mese"]
    buttons = ["scarica"]

    def col_cliente(self, obj):
        return obj.fattura.cliente
    col_cliente.short_description = "Cliente"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("fattura__cliente")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def scarica(self, request, obj):
        return redirect(reverse("sdi:xml", args=[obj.pk]))
    scarica.short_description = "Scarica l'XML"
    scarica.ai = False
    scarica.permission = "view"


@register
class NotificaSdiView(ModelView):
    model = NotificaSdi
    slug = "notifiche"
    list_display = ["nome_file", "tipo", "trasmissione", "identificativo_sdi", "ricevuta_il"]
    list_filter = ["tipo", "ricevuta_il"]
    search_fields = ["nome_file", "identificativo_sdi", "file_fattura"]
    form_layout = [("Notifica", [("tipo", "nome_file"), ("trasmissione", "identificativo_sdi"), "ricevuta_il"])]
    readonly_fields = ["tipo", "nome_file", "trasmissione", "identificativo_sdi", "ricevuta_il"]

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("trasmissione")
        azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
        return qs.filter(azienda_id=azienda_id) if azienda_id is not None else qs.none()

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def euro(valore):
    from core.viste.gruppi import numero
    return f"{numero(valore)} €"


@register
class FatturaPassivaView(ModelView):
    model = FatturaPassiva
    slug = "passive"
    list_display = ["numero", "data", "fornitore", "totale", "stato", "pagata"]
    list_filter = ["stato", "pagata", "fornitore", "data", "tipo_documento"]
    search_fields = ["numero", "fornitore__nome", "fornitore__partita_iva", "causale", "identificativo_sdi"]
    form_layout = [("Fattura", [("fornitore", "tipo_documento"), ("numero", "data"), "causale"]),
                   ("Importi", [("imponibile", "imposta", "totale")]),
                   ("Ricezione", [("nome_file", "identificativo_sdi"), ("ricevuta_il", "registrata_il"), "stato"]),
                   ("Note", ["note"])]
    readonly_fields = ["fornitore", "tipo_documento", "numero", "data", "causale", "imponibile", "imposta", "totale",
                       "nome_file", "identificativo_sdi", "ricevuta_il", "registrata_il", "stato", "pagata"]
    company_field = "azienda"
    inlines = [Inline(RigaPassiva, "fattura", ["descrizione", "quantita", "unita", "prezzo", "importo", "aliquota",
                                                "natura"], titolo="Righe")]
    list_group_by = ["stato", "fornitore", "data:mese"]
    list_sum = ["imponibile", "imposta", "totale"]
    graph = {"tipi": ["barre", "torta"], "misure": ["sum:imponibile", "sum:totale", "count"],
             "per": ["data:mese", "fornitore"]}
    chatter = True
    tracked_fields = ["stato", "note"]
    buttons = ["registra", "forza", "contesta", "scarica"]
    actions = ["registra_selezionate"]

    def col_totale(self, obj):
        return euro(-obj.totale if obj.nota_credito else obj.totale)
    col_totale.short_description = "Totale"

    def has_add_permission(self, request):
        return False                                   # arrivano dallo SDI o da «Carica file dello SDI»

    def totali(self, obj):
        voci = [(f"Imponibile {r.aliquota:.0f}%{' ' + r.natura if r.natura else ''}", euro(r.imponibile))
                for r in obj.riepilogo.all()]
        return voci + [("IVA", euro(obj.imposta)), ("Totale", euro(obj.totale))]

    def get_buttons(self, request, obj):
        ammessi = {"scarica"} | ({"registra", "forza", "contesta"} if obj.stato == FatturaPassiva.DA_VERIFICARE else set())
        return [(n, e) for n, e in super().get_buttons(request, obj) if n in ammessi]

    def registra(self, request, obj):
        from django.core.exceptions import ValidationError
        try:
            passive.registra(obj)
        except ValidationError as e:
            return " ".join(e.messages)
        return f"Fattura {obj.numero} registrata."
    registra.short_description = "Registra"

    def forza(self, request, obj):
        passive.registra(obj, forza=True)
        from core import chatter
        chatter.scrivi(obj, request.user, "Registrata nonostante il confronto con l'ordine.", tipo="nota")
        return f"Fattura {obj.numero} registrata comunque."
    forza.short_description = "Registra comunque"
    forza.rischio = "irreversibile"
    forza.permission = "sdi.delete_fatturapassiva"

    def contesta(self, request, obj):
        obj.stato = FatturaPassiva.CONTESTATA
        obj.save(update_fields=["stato"])
        return "Fattura segnata come contestata: chiedi al fornitore una nota di credito."
    contesta.short_description = "Contesta"
    contesta.rischio = "irreversibile"

    def scarica(self, request, obj):
        return redirect(reverse("sdi:originale", args=[obj.pk]))
    scarica.short_description = "Scarica il file"
    scarica.ai = False
    scarica.permission = "view"

    def registra_selezionate(self, request, queryset):
        from django.core.exceptions import ValidationError
        n, ferme = 0, []
        for f in queryset.filter(stato=FatturaPassiva.DA_VERIFICARE):
            try:
                passive.registra(f)
                n += 1
            except ValidationError:
                ferme.append(f.numero)
        return f"Fatture registrate: {n}." + (f" Ferme per il confronto con l'ordine: {', '.join(ferme)}." if ferme else "")
    registra_selezionate.short_description = "Registra"


@register
class ScadenzaPassivaView(ModelView):
    model = ScadenzaPassiva
    slug = "pagamenti"
    verbose_name_plural = "scadenze da pagare"
    list_display = ["fattura", "fornitore", "data", "importo", "residuo", "modalita", "pagata", "pagata_il"]
    list_filter = ["pagata", "data", "fattura__fornitore"]
    search_fields = ["fattura__numero", "fattura__fornitore__nome"]
    form_layout = [("Scadenza", [("fattura", "data"), ("importo", "modalita"), "iban", ("pagata", "pagata_il"), "pagato"])]
    readonly_fields = ["fattura", "data", "importo", "modalita", "iban", "pagata", "pagata_il", "pagato"]
    ordering = ["pagata", "data"]
    list_sum = ["importo"]
    list_group_by = ["pagata", "data:mese"]
    actions = ["paga_selezionate"]
    buttons = ["paga", "registra"]
    chatter = True
    tracked_fields = ["pagata"]

    def col_residuo(self, obj):
        return euro(obj.residuo)
    col_residuo.short_description = "Da pagare"

    def indirizzi_suggeriti(self, obj):
        return super().indirizzi_suggeriti(obj.fattura.fornitore) if obj.fattura_id and obj.fattura.fornitore_id else []

    def col_fornitore(self, obj):
        return obj.fattura.fornitore
    col_fornitore.short_description = "Fornitore"

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("fattura__fornitore")
        azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
        return qs.filter(fattura__azienda_id=azienda_id) if azienda_id is not None else qs.none()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_buttons(self, request, obj):
        return [] if obj.pagata else super().get_buttons(request, obj)

    def paga(self, request, obj):
        residuo = obj.residuo
        passive.paga(obj, utente=request.user)
        return f"Pagati {euro(residuo)} a {obj.fattura.fornitore}."
    paga.short_description = "Segna pagata"

    def registra(self, request, obj):
        return redirect("sdi:pagamento_passivo", pk=obj.pk)
    registra.short_description = "Pagamento parziale o abbuono"
    registra.ai = False

    def paga_selezionate(self, request, queryset):
        scadenze = list(queryset.filter(pagata=False).select_related("fattura"))
        for s in scadenze:
            passive.paga(s, utente=request.user)
        return f"Scadenze pagate: {len(scadenze)}."
    paga_selezionate.short_description = "Segna pagate"
