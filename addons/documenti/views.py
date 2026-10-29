import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils import timezone

from core.viste import Inline, ModelView, register

from . import accesso, quote, richieste, servizi
from .models import Cartella, Condivisione, Documento, MembroSpazio, QuotaUtente, Richiesta, Spazio, Tag


@register
class CartellaView(ModelView):
    model = Cartella
    slug = "cartelle"
    list_display = ["__str__", "modello"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Cartella", [("nome", "padre"), "descrizione"]),
                   ("Permessi", [("gruppi_lettura", "gruppi_scrittura")]),
                   ("Allegati dei record", ["modello"])]
    company_field = "azienda"

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None:
            return base

        class Form(base):
            def clean_modello(self):
                modello = self.cleaned_data.get("modello")
                altre = Cartella.objects.filter(azienda=request.azienda, modello=modello).exclude(pk=self.instance.pk)
                if modello and altre.exists():
                    raise ValidationError("Un'altra cartella raccoglie già gli allegati di questo tipo di record.")
                return modello
        return Form

    def col___str__(self, obj):
        return obj.percorso()
    col___str__.short_description = "Cartella"


@register
class TagView(ModelView):
    model = Tag
    slug = "tag"
    list_display = ["nome", "colore"]
    search_fields = ["nome"]
    form_layout = [("Tag", [("nome", "colore")])]


@register
class DocumentoView(ModelView):
    model = Documento
    slug = "documenti"
    list_display = ["nome", "cartella", "proprietario", "dimensione", "creato"]
    list_filter = ["cartella", "tag", "proprietario", "creato"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Documento", [("nome", "cartella"), "tag", "descrizione"]), ("Altro", ["@proprieta"])]
    readonly_fields = ["mime", "dimensione", "proprietario", "bloccato_da", "creato", "modificato"]
    company_field = "azienda"
    list_group_by = ["cartella", "proprietario", "creato:mese"]
    chatter = True
    tracked_fields = ["nome", "cartella"]
    buttons = ["scarica", "blocca", "sblocca", "cestina"]

    def col_dimensione(self, obj):
        return filesizeformat(obj.dimensione)
    col_dimensione.short_description = "Dimensione"

    def get_queryset(self, request):
        qs = super().get_queryset(request).filter(cestinato_il__isnull=True).select_related("cartella", "proprietario")
        if accesso.gestore(request.user):
            return qs
        return qs.filter(cartella__in=[c.pk for c in accesso.visibili(request.user, request.azienda)])

    def has_add_permission(self, request):
        return False                                  # si carica dall'archivio

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or accesso.puo_modificare(request.user, obj))

    def has_delete_permission(self, request, obj=None):
        return False                                  # si passa dal cestino

    def get_buttons(self, request, obj):
        nascosti = {"blocca"} if obj.bloccato_da_id else {"sblocca"}
        if not accesso.puo_modificare(request.user, obj):
            nascosti |= {"blocca", "sblocca", "cestina"}
        return [(n, e) for n, e in super().get_buttons(request, obj) if n not in nascosti]

    def scarica(self, request, obj):
        return redirect(reverse("documenti:scarica", args=[obj.pk]))
    scarica.short_description = "Scarica"
    scarica.ai = False
    scarica.permission = "view"

    def blocca(self, request, obj):
        obj.bloccato_da = request.user
        obj.save(update_fields=["bloccato_da"])
        return f"«{obj}» bloccato: solo tu puoi modificarlo."
    blocca.short_description = "Blocca"

    def sblocca(self, request, obj):
        obj.bloccato_da = None
        obj.save(update_fields=["bloccato_da"])
        return f"«{obj}» sbloccato."
    sblocca.short_description = "Sblocca"

    def cestina(self, request, obj):
        servizi.cestina([obj])
        messages.success(request, f"«{obj}» spostato nel cestino.")
        return redirect(f"{reverse('documenti:archivio')}?cartella={obj.cartella_id}")
    cestina.short_description = "Sposta nel cestino"


@register
class CondivisioneView(ModelView):
    model = Condivisione
    slug = "condivisioni"
    list_display = ["nome", "cartella", "scadenza", "stato", "consente_caricamento", "creata_da"]
    list_filter = ["consente_caricamento", "scadenza", "creata_da"]
    search_fields = ["nome"]
    form_layout = [("Condivisione", [("nome", "scadenza"), "cartella", "documenti", "consente_caricamento"])]
    readonly_fields = ["creata_da", "creata"]
    company_field = "azienda"
    buttons = ["revoca"]

    def col_stato(self, obj):
        return "revocata" if obj.revocata else "attiva" if obj.attiva else "scaduta"
    col_stato.short_description = "Stato"

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None:
            return base
        visibili = [c.pk for c in accesso.visibili(request.user, request.azienda)]

        class Form(base):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if not self.instance.pk:
                    self.initial.setdefault("scadenza", timezone.localdate() + datetime.timedelta(days=30))
                self.fields["cartella"].queryset = Cartella.objects.filter(pk__in=visibili)
                self.fields["documenti"].queryset = Documento.objects.filter(cartella__in=visibili,
                                                                             cestinato_il__isnull=True)

            def clean(self):
                dati = super().clean()
                if not dati.get("cartella") and not dati.get("documenti"):
                    raise ValidationError("Condividi una cartella o almeno un documento.")
                if dati.get("consente_caricamento") and not dati.get("cartella"):
                    self.add_error("consente_caricamento", "Per ricevere file serve una cartella.")
                elif dati.get("consente_caricamento") and not accesso.puo_scrivere(request.user, dati["cartella"]):
                    self.add_error("consente_caricamento", "Non puoi caricare in questa cartella.")
                return dati
        return Form

    def save_model(self, request, obj, form, change):
        if not change:
            obj.creata_da = request.user
        super().save_model(request, obj, form, change)

    def get_buttons(self, request, obj):
        return [] if obj.revocata else super().get_buttons(request, obj)

    def revoca(self, request, obj):
        obj.revocata = True
        obj.save(update_fields=["revocata"])
        return f"Il link «{obj}» non funziona più."
    revoca.short_description = "Revoca il link"
    revoca.rischio = "irreversibile"


@register
class RichiestaView(ModelView):
    model = Richiesta
    slug = "richieste"
    list_display = ["titolo", "destinatario", "scadenza", "stato", "cartella", "richiesta_da"]
    list_filter = ["stato", "destinatario", "scadenza"]
    search_fields = ["titolo", "descrizione"]
    form_layout = [("Richiesta", ["titolo", ("destinatario", "scadenza"), "cartella", "descrizione"])]
    readonly_fields = ["stato", "richiesta_da", "documento", "creata"]
    company_field = "azienda"
    list_group_by = ["stato", "destinatario"]
    kanban_group = "stato"
    kanban_fields = ["destinatario", "scadenza"]
    chatter = True
    tracked_fields = ["stato", "destinatario", "scadenza"]
    buttons = ["annulla"]

    def get_form_class(self, request=None):
        base = super().get_form_class(request)
        if request is None:
            return base
        visibili = [c.pk for c in accesso.visibili(request.user, request.azienda)]

        class Form(base):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.fields["cartella"].queryset = Cartella.objects.filter(pk__in=visibili)
                if not self.instance.pk:
                    self.initial.setdefault("scadenza", timezone.localdate() + datetime.timedelta(days=7))
        return Form

    def has_view_permission(self, request, obj=None):
        """Il destinatario vede la richiesta che gli è stata fatta anche senza i permessi sui documenti."""
        return super().has_view_permission(request, obj) or (obj is not None and obj.destinatario_id == request.user.pk)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (obj is None or obj.stato == Richiesta.APERTA)

    def save_model(self, request, obj, form, change):
        nuova = not change
        if nuova:
            obj.richiesta_da = request.user
        super().save_model(request, obj, form, change)
        if nuova:
            richieste.apri(obj, request.user)

    def get_buttons(self, request, obj):
        return super().get_buttons(request, obj) if obj.stato == Richiesta.APERTA else []

    def annulla(self, request, obj):
        if request.user.pk not in (obj.richiesta_da_id, obj.destinatario_id) and not accesso.gestore(request.user):
            raise PermissionDenied
        richieste.annulla(obj, request.user)
        return f"Richiesta «{obj}» annullata."
    annulla.short_description = "Annulla la richiesta"


@register
class SpazioView(ModelView):
    """Spazi di lavoro: chi li gestisce sceglie i membri; la quota di uno spazio condiviso la fissano i responsabili."""
    model = Spazio
    slug = "spazi"
    verbose_name_plural = "spazi di lavoro"
    list_display = ["nome", "tipo", "proprietario", "uso"]
    list_filter = ["tipo", "proprietario"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Spazio", [("nome", "quota_mb"), "descrizione"])]
    company_field = "azienda"
    inlines = [Inline(MembroSpazio, "spazio", ["utente", "ruolo"], titolo="Membri (solo per gli spazi condivisi)")]

    def get_queryset(self, request):
        """I responsabili vedono tutti gli spazi; gli altri quelli che gestiscono."""
        qs = super().get_queryset(request)
        if accesso.gestore(request.user):
            return qs
        gestiti = [s.pk for s, (_, _, gestisce) in accesso.spazi(request.user, request.azienda).items() if gestisce]
        return qs.filter(pk__in=gestiti)

    def has_add_permission(self, request):
        return False                                   # si crea dall'archivio, con la sua cartella radice

    def has_delete_permission(self, request, obj=None):
        return accesso.gestore(request.user)

    def save_model(self, request, obj, form, change):
        if change and not accesso.gestore(request.user):   # la quota la decidono i responsabili
            obj.quota_mb = Spazio.objects.get(pk=obj.pk).quota_mb
        super().save_model(request, obj, form, change)

    def col_uso(self, obj):
        r = quote.riepilogo(obj)
        return filesizeformat(r["usato"]) + (f" di {filesizeformat(r['quota'])}" if r["quota"] else "")
    col_uso.short_description = "Spazio usato"


@register
class QuotaUtenteView(ModelView):
    """Come l'azienda suddivide la sua quota: i MB di ogni utente per i suoi spazi personali."""
    model = QuotaUtente
    slug = "quote"
    verbose_name_plural = "quote degli utenti"
    list_display = ["utente", "quota_mb", "uso"]
    search_fields = ["utente__username", "utente__first_name", "utente__last_name"]
    form_layout = [("Quota", [("utente", "quota_mb")])]
    company_field = "azienda"

    def col_uso(self, obj):
        return filesizeformat(quote.uso_personale(obj.utente, obj.azienda))
    col_uso.short_description = "Usati"
