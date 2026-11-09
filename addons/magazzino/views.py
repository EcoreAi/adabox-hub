from django.apps import apps
from django.core.exceptions import ValidationError

from core.viste import Inline, ModelView, register, schede

from . import operazioni
from .models import Consegna, Magazzino, Movimento, Ricevimento, RigaConsegna, RigaRicevimento, Ubicazione
from .models import Inventario, Lotto, ScortaMagazzino


@register
class MagazzinoView(ModelView):
    model = Magazzino
    slug = "magazzini"
    list_display = ["nome", "indirizzo", "predefinito"]
    form_layout = [("Magazzino", ["nome", "indirizzo", "predefinito"])]
    company_field = "azienda"


@register
class UbicazioneView(ModelView):
    """Zone, scaffali e celle dei magazzini, una dentro l'altra."""
    model = Ubicazione
    slug = "ubicazioni"
    list_display = ["codice", "nome", "magazzino", "padre", "predefinita", "attiva"]
    list_filter = ["magazzino", "attiva"]
    search_fields = ["codice", "nome"]
    form_layout = [("Ubicazione", [("magazzino", "padre"), ("codice", "nome"), ("predefinita", "attiva")])]
    company_field = "azienda"
    list_group_by = ["magazzino"]
    ai_descrizione = "Le ubicazioni dei magazzini (zone, scaffali, celle), ad albero, con la merce che contengono."


@register
class LottoView(ModelView):
    """Lotti e numeri di serie: nascono dai ricevimenti; la scheda mostra da chi è arrivato e a chi è andato."""
    model = Lotto
    slug = "lotti"
    list_display = ["codice", "prodotto", "scadenza", "giacenza", "seriale"]
    list_filter = ["prodotto", "seriale", "scadenza"]
    search_fields = ["codice", "prodotto__nome", "prodotto__codice", "note"]
    form_layout = [("Lotto", [("prodotto", "codice"), "scadenza", "note"])]
    company_field = "azienda"
    list_group_by = ["prodotto", "scadenza:mese"]
    ai_descrizione = "Lotti e numeri di serie dei beni, con scadenza, giacenza e tracciabilità verso fornitori e clienti."
    chatter = True                # richiami, non conformità e reclami restano sul lotto
    tracked_fields = ["scadenza"]

    def col_giacenza(self, obj):
        from .lotti import saldo
        return f"{saldo(obj):g}"
    col_giacenza.short_description = "Giacenza"


@register
class MovimentoView(ModelView):
    """Movimenti: nascono da consegne e ricevimenti; a mano solo le rettifiche (inventario, scarti)."""
    model = Movimento
    slug = "movimenti"
    list_display = ["data", "prodotto", "lotto", "magazzino", "ubicazione", "tipo", "quantita", "costo_unitario", "valore_movimento", "causale"]
    list_filter = ["tipo", "magazzino", "ubicazione", "prodotto", "lotto", "data"]
    search_fields = ["prodotto__nome", "prodotto__codice", "causale", "lotto__codice"]
    form_layout = [("Rettifica", [("prodotto", "magazzino"), ("ubicazione", "lotto"), ("quantita", "costo_unitario"), "causale"])]
    company_field = "azienda"
    list_group_by = ["prodotto", "tipo", "magazzino", "data:mese"]
    list_sum = ["quantita", "valore"]
    api = True

    def has_change_permission(self, request, obj=None):
        return False                                   # i movimenti non si correggono: si rettifica

    def has_delete_permission(self, request, obj=None):
        return False

    def col_valore_movimento(self, obj):
        return "—" if obj.valore is None else f"{obj.valore:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    col_valore_movimento.short_description = "Valore (€)"

    def save_model(self, request, obj, form, change):
        obj.tipo, obj.utente = Movimento.RETTIFICA, request.user
        super().save_model(request, obj, form, change)


def _bottone(request, funzione, obj, messaggio):
    try:
        funzione(obj, request.user)
    except ValidationError as e:
        return " ".join(e.messages)
    return messaggio(obj)


def _leggi(obj, tipo):
    from django.shortcuts import redirect
    if obj.stato not in obj.APERTI:
        return "Il documento non è più da evadere."
    return redirect("magazzino:lettura_documento", tipo=tipo, pk=obj.pk)


@register
class ConsegnaView(ModelView):
    model = Consegna
    slug = "consegne"
    list_display = ["documento", "cliente", "data", "riferimento", "stato"]
    list_filter = ["stato", "cliente", "magazzino", "data"]
    search_fields = ["numero", "riferimento", "cliente__nome"]
    form_layout = [("Consegna", [("cliente", "magazzino"), "destinazione", ("data", "riferimento"), ("causale_trasporto", "trasporto_a_cura"),
                                 ("vettore", "colli"), ("peso", "aspetto_beni"), "note"])]
    readonly_fields = ["numero", "stato"]
    company_field = "azienda"
    inlines = [Inline(RigaConsegna, "consegna", ["prodotto", "descrizione", "quantita", "ubicazione", "lotti"], titolo="Merce")]
    kanban_group = "stato"
    kanban_fields = ["cliente", "data", "riferimento"]
    kanban_ricco = True
    kanban_colori = {"bozza": "azzurro", "pronto": "viola", "fatto": "verde", "annullato": "grigio"}
    chatter = True
    tracked_fields = ["stato"]
    buttons = ["preleva", "leggi_codici", "pronta", "spedisci", "annulla", "storna"]
    actions = ["fattura_differita"]
    reports = [{"nome": "DDT", "template": "magazzino/report/ddt.html", "colonne": [("codice", "Codice articolo"), ("um", "Unità di misura")]}]
    api = True


    def kanban_queryset(self, qs):
        return qs.select_related("cliente")

    def kanban_scheda(self, request, obj):
        esito = {"fatto": (*schede.FATTO, "Spedita"), "annullato": (*schede.FERMO, "Annullato"),
                 "pronto": ("viola", "icon-check", "Pronta")}.get(obj.stato) or ("azzurro", "icon-calendar", "Da spedire")
        return schede.scheda(esito, sottotitolo=obj.cliente.nome, righe=[r for r in (f"Del {obj.data:%d/%m/%Y}", obj.riferimento) if r])

    def col_documento(self, obj):
        return str(obj)
    col_documento.short_description = "Documento"

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato in Consegna.APERTI)

    def get_buttons(self, request, obj):
        tutti = super().get_buttons(request, obj)
        if obj.stato == Consegna.FATTO:
            return [b for b in tutti if b[0] in ("storna", "preleva")]
        if obj.stato == Consegna.ANNULLATO:
            return []
        return [b for b in tutti if b[0] != "storna" and not (b[0] == "pronta" and obj.stato == Consegna.PRONTO)]

    def get_actions(self, request):
        azioni = super().get_actions(request)
        return azioni if apps.is_installed("fatturazione") and request.user.has_perm("fatturazione.add_fattura") else [
            (n, e) for n, e in azioni if n != "fattura_differita"]

    def fattura_differita(self, request, queryset):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.urls import reverse
        from fatturazione import operazioni as fatturazione
        try:
            fattura = fatturazione.da_consegne(list(queryset))
        except ValidationError as e:
            return " ".join(e.messages)
        messages.success(request, f"{fattura} creata con {fattura.ddt.count()} DDT: controllala ed emettila.")
        return redirect(reverse("fatturazione:fatture_dettaglio", args=[fattura.pk]))
    fattura_differita.short_description = "Crea fattura differita"

    def spedisci(self, request, obj):
        return _bottone(request, operazioni.spedisci, obj, lambda c: f"Consegna spedita con il DDT {c.numero}.")
    spedisci.short_description = "Spedisci (emetti DDT)"
    spedisci.rischio = "irreversibile"

    def preleva(self, request, obj):
        from django.shortcuts import redirect
        return redirect("magazzino:prelievo", pk=obj.pk)
    preleva.short_description = "Prelievo e colli"
    preleva.ai = False

    def pronta(self, request, obj):
        return _bottone(request, operazioni.segna_pronta, obj, lambda c: "Consegna pronta: merce preparata, da spedire.")
    pronta.short_description = "Segna pronta"

    def storna(self, request, obj):
        return _bottone(request, operazioni.storna, obj, lambda c: "Consegna stornata: la merce è tornata a magazzino.")
    storna.short_description = "Storna"
    storna.rischio = "irreversibile"
    storna.permission = "magazzino.add_movimento"

    def annulla(self, request, obj):
        if obj.stato not in Consegna.APERTI:
            return "Solo una consegna da spedire si annulla."
        obj.stato = Consegna.ANNULLATO
        obj.save(update_fields=["stato"])
        return "Consegna annullata."
    annulla.short_description = "Annulla"

    def leggi_codici(self, request, obj):
        return _leggi(obj, "consegna")
    leggi_codici.short_description = "Leggi i codici"
    leggi_codici.ai = False


@register
class RicevimentoView(ModelView):
    model = Ricevimento
    slug = "ricevimenti"
    list_display = ["fornitore", "data", "riferimento", "ddt_fornitore", "stato"]
    list_filter = ["stato", "fornitore", "magazzino", "data"]
    search_fields = ["riferimento", "ddt_fornitore", "fornitore__nome"]
    form_layout = [("Ricevimento", [("fornitore", "magazzino"), ("data", "ddt_fornitore"), "riferimento", "note"])]
    readonly_fields = ["stato"]
    company_field = "azienda"
    inlines = [Inline(RigaRicevimento, "ricevimento", ["prodotto", "quantita", "costo", "ubicazione", "lotti"], titolo="Merce")]
    kanban_group = "stato"
    kanban_fields = ["fornitore", "data"]
    kanban_ricco = True
    kanban_colori = {"bozza": "azzurro", "fatto": "verde", "annullato": "grigio"}
    chatter = True
    tracked_fields = ["stato"]
    buttons = ["leggi_codici", "ricevi", "annulla", "storna"]
    api = True


    def kanban_queryset(self, qs):
        return qs.select_related("fornitore")

    def kanban_scheda(self, request, obj):
        esito = {"fatto": (*schede.FATTO, "Ricevuto"), "annullato": (*schede.FERMO, "Annullato")}.get(obj.stato) or ("azzurro", "icon-calendar", "Da ricevere")
        return schede.scheda(esito, sottotitolo=obj.fornitore.nome, righe=[r for r in (f"Del {obj.data:%d/%m/%Y}", obj.riferimento) if r])

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato == Ricevimento.BOZZA)

    def get_buttons(self, request, obj):
        tutti = super().get_buttons(request, obj)
        if obj.stato == Ricevimento.FATTO:
            return [b for b in tutti if b[0] == "storna"]
        return [b for b in tutti if b[0] != "storna"] if obj.stato == Ricevimento.BOZZA else []

    def annulla(self, request, obj):
        if obj.stato != Ricevimento.BOZZA:
            return "Solo un ricevimento da ricevere si annulla."
        obj.stato = Ricevimento.ANNULLATO
        obj.save(update_fields=["stato"])
        return "Ricevimento annullato."
    annulla.short_description = "Annulla"

    def storna(self, request, obj):
        return _bottone(request, operazioni.storna, obj, lambda r: "Ricevimento stornato: la merce è uscita dal magazzino.")
    storna.short_description = "Storna"
    storna.rischio = "irreversibile"
    storna.permission = "magazzino.add_movimento"

    def ricevi(self, request, obj):
        return _bottone(request, operazioni.ricevi, obj, lambda r: "Merce ricevuta e caricata a magazzino.")

    def leggi_codici(self, request, obj):
        return _leggi(obj, "ricevimento")
    leggi_codici.short_description = "Leggi i codici"
    leggi_codici.ai = False
    ricevi.short_description = "Ricevi la merce"
    ricevi.rischio = "irreversibile"


@register
class InventarioView(ModelView):
    """Gli inventari: alla creazione si fotografa il teorico, poi si conta e si approva."""
    model = Inventario
    slug = "inventari"
    company_field = "azienda"
    list_display = ["numero", "data", "magazzino", "ubicazione", "categoria", "stato", "ciclica"]
    list_filter = ["stato", "magazzino", "ciclica"]
    search_fields = ["numero", "note"]
    form_layout = [("Inventario", [("magazzino", "data"), ("ubicazione", "categoria"), "note"])]
    readonly_fields = ["numero", "stato", "ciclica", "creato_da", "approvato_da", "approvato_il"]
    buttons = ["conta", "annulla"]
    ai_descrizione = "Gli inventari di magazzino: conta della merce, differenze e rettifiche."

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creato_da = request.user
        super().save_model(request, obj, form, change)
        if not change:
            from . import inventari
            inventari.fotografa(obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato == obj.CONTA)

    def get_buttons(self, request, obj):
        return super().get_buttons(request, obj) if obj.stato == obj.CONTA else []

    def conta(self, request, obj):
        from django.shortcuts import redirect
        return redirect("magazzino:inventario_conta", pk=obj.pk)
    conta.short_description = "Conta"
    conta.ai = False

    def annulla(self, request, obj):
        obj.stato = obj.ANNULLATO
        obj.save(update_fields=["stato"])
        return "Inventario annullato: nessuna rettifica."
    annulla.short_description = "Annulla"


@register
class ScortaMagazzinoView(ModelView):
    """Scorta per magazzino: dove c'è, il riordino guarda quel magazzino invece del totale."""
    model = ScortaMagazzino
    slug = "scorte"
    company_field = "azienda"
    list_display = ["magazzino", "prodotto", "punto_riordino", "scorta_obiettivo"]
    list_filter = ["magazzino"]
    search_fields = ["prodotto__nome", "prodotto__codice"]
    form_layout = [("Scorta", [("magazzino", "prodotto"), ("punto_riordino", "scorta_obiettivo")])]
    ai_descrizione = "Punti di riordino e scorte obiettivo dei prodotti per singolo magazzino."
