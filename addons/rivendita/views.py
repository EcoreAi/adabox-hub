from django.utils import timezone

from core.viste import ModelView, register

from .models import Istanza, ModuloVendibile, Pacchetto, Piano, Richiesta


@register
class IstanzeView(ModelView):
    model = Istanza
    slug = "istanze"
    list_display = ["cliente", "piano", "scadenza", "ultimo_contatto", "utenti_attivi", "ospitata", "attiva"]
    list_filter = ["piano", "ospitata", "attiva", "scadenza"]
    search_fields = ["cliente", "email", "url"]
    form_layout = [("Cliente", [("cliente", "email"), ("url", "ospitata")]),
                   ("Licenza", [("piano", "scadenza"), ("utenti", "grazia_giorni"), "moduli_extra", "attiva"]),
                   ("Stato", [("ultimo_contatto", "utenti_attivi"), "codice"]), ("Note", ["note"])]
    readonly_fields = ["ultimo_contatto", "utenti_attivi", "codice"]
    list_group_by = ["piano", "ospitata", "scadenza:mese"]
    buttons = ["genera_token"]

    def genera_token(self, request, obj):
        return (f"Token di {obj.cliente}: {obj.nuovo_token()} (si vede solo adesso: va in LICENZA_TOKEN sull'istanza; "
                f"quello di prima non vale più).")
    genera_token.short_description = "Genera il token"
    genera_token.rischio = "irreversibile"
    genera_token.ai = False


@register
class RichiesteView(ModelView):
    model = Richiesta
    slug = "richieste"
    list_display = ["creata", "istanza", "nome", "tipo", "utente", "stato"]
    list_filter = ["stato", "tipo", "istanza"]
    search_fields = ["nome", "slug", "nota"]
    form_layout = [("Richiesta", [("istanza", "nome"), ("tipo", "utente"), "creata", "nota", ("stato", "decisa_il"), "decisa_da"])]
    readonly_fields = ["istanza", "nome", "tipo", "utente", "creata", "nota", "stato", "decisa_il", "decisa_da"]
    list_group_by = ["stato", "istanza", "nome"]
    buttons = ["approva", "gestita", "rifiuta"]

    def has_add_permission(self, request):
        return False

    def get_buttons(self, request, obj):
        if obj.stato != Richiesta.NUOVA:
            return []
        fuori = "approva" if obj.tipo == Richiesta.DEMO else "gestita"     # una demo non entra in licenza
        return [(n, e) for n, e in super().get_buttons(request, obj) if n != fuori]

    def _decidi(self, request, obj, stato):
        obj.stato, obj.decisa_il, obj.decisa_da = stato, timezone.now(), request.user
        obj.save(update_fields=["stato", "decisa_il", "decisa_da"])

    def gestita(self, request, obj):
        self._decidi(request, obj, Richiesta.APPROVATA)
        return f"Demo di {obj.nome} per {obj.istanza} segnata come gestita."
    gestita.short_description = "Demo gestita"

    def approva(self, request, obj):
        modulo = ModuloVendibile.objects.filter(slug=obj.slug).first()
        if modulo is None:
            return f"Il modulo {obj.slug} non è più in vendita."
        obj.istanza.moduli_extra.add(modulo)
        self._decidi(request, obj, Richiesta.APPROVATA)
        return f"{modulo} aggiunto a {obj.istanza}: l'istanza lo installa alla prossima sincronizzazione."
    approva.short_description = "Approva e attiva"

    def rifiuta(self, request, obj):
        self._decidi(request, obj, Richiesta.RIFIUTATA)
        return f"Richiesta di {obj.nome} rifiutata."
    rifiuta.short_description = "Rifiuta"


@register
class PianiView(ModelView):
    model = Piano
    slug = "piani"
    list_display = ["nome", "prezzo_mese", "utenti", "attivo"]
    list_filter = ["attivo"]
    search_fields = ["nome"]
    form_layout = [("Piano", [("nome", "attivo"), ("prezzo_mese", "utenti"), "moduli", "descrizione"])]


@register
class ModuliView(ModelView):
    model = ModuloVendibile
    slug = "moduli"
    list_display = ["nome", "slug", "categoria", "prezzo_mese", "application", "in_catalogo", "su_misura"]
    list_filter = ["categoria", "application", "in_catalogo", "su_misura"]
    search_fields = ["nome", "slug"]
    form_layout = [("Modulo", [("nome", "slug"), ("categoria", "prezzo_mese"), "riassunto", ("application", "in_catalogo", "su_misura")]),
                   ("Scheda nel catalogo", ["descrizione", "funzioni", "url_demo"])]
    readonly_fields = ["slug"]

    def has_add_permission(self, request):
        return False


@register
class PacchettiView(ModelView):
    model = Pacchetto
    slug = "pacchetti"
    list_display = ["modulo", "versione", "min_core", "dimensione", "pubblicato", "creato"]
    list_filter = ["modulo", "pubblicato"]
    search_fields = ["nome_file", "sha256"]
    form_layout = [("Pacchetto", [("modulo", "versione"), ("nome_file", "dimensione"), ("min_core", "creato"), "sha256", "pubblicato"])]
    readonly_fields = ["modulo", "versione", "nome_file", "dimensione", "min_core", "creato", "sha256"]

    def has_add_permission(self, request):
        return False
