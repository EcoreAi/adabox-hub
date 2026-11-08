from core.viste import ModelView, register

from .models import Distinta, Mandato


def euro(valore):
    return f"{valore:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


@register
class MandatoView(ModelView):
    """I mandati SEPA firmati dai clienti: senza un mandato attivo non si fa l'addebito SDD."""
    model = Mandato
    slug = "mandati"
    company_field = "azienda"
    list_display = ["riferimento", "contatto", "iban", "schema", "data_firma", "attivo"]
    list_filter = ["schema", "attivo"]
    search_fields = ["riferimento", "contatto__nome", "iban"]
    form_layout = [("Mandato", [("contatto", "riferimento"), ("iban", "bic"), ("data_firma", "schema"), ("attivo", "revocato_il"),
                                "note"])]
    chatter = True
    tracked_fields = ["attivo", "revocato_il", "iban"]
    ai_descrizione = "I mandati SEPA dei clienti per gli addebiti diretti SDD: riferimento, IBAN, data di firma, schema CORE o B2B."


@register
class DistintaView(ModelView):
    """Le distinte presentate alla banca. Si creano da «Nuova distinta», scegliendo le scadenze."""
    model = Distinta
    slug = "distinte"
    company_field = "azienda"
    list_display = ["numero", "tipo", "data", "conto", "voci_n", "totale", "stato"]
    list_filter = ["tipo", "stato", "conto"]
    search_fields = ["identificativo", "voci__nome", "note"]
    readonly_fields = ["tipo", "conto", "data", "stato", "identificativo", "presentata_il", "utente", "creata"]
    form_layout = [("Distinta", [("tipo", "conto"), ("data", "stato"), ("identificativo", "presentata_il"), ("utente", "creata"), "note"])]
    ai_descrizione = "Le distinte di bonifici SEPA ai fornitori, addebiti SDD e RiBa ai clienti, con le voci e gli esiti."
    chatter = True
    tracked_fields = ["stato"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or obj.stato == Distinta.BOZZA)

    def col_numero(self, obj):
        return f"N. {obj.pk}"
    col_numero.short_description = "Distinta"

    def col_voci_n(self, obj):
        return obj.voci.count()
    col_voci_n.short_description = "Voci"

    def col_totale(self, obj):
        return euro(obj.totale)
    col_totale.short_description = "Totale"
