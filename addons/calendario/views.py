from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect

from core import lavori
from django.urls import reverse

from core.viste import Inline, ModelView, register

from . import prenotazioni

from .ics import ics
from .models import Evento, OrarioAppuntamento, Prenotazione, TipoAppuntamento


@register
class EventoView(ModelView):
    model = Evento
    slug = "eventi"
    list_display = ["titolo", "inizio", "fine", "luogo", "organizzatore"]
    list_filter = ["organizzatore", "privato", "inizio"]
    search_fields = ["titolo", "luogo", "descrizione"]
    ordering = ["-inizio"]
    form_layout = [
        ("Evento", ["titolo", ("inizio", "fine"), ("tutto_il_giorno", "privato"), "luogo", "descrizione"]),
        ("Persone", ["partecipanti", "contatti", "promemoria"]),
    ]
    company_field = "azienda"
    calendar_date = "inizio"
    list_group_by = ["organizzatore", "inizio:mese"]
    graph = {"tipi": ["barre", "linee"], "misure": ["count"], "per": ["inizio:mese", "organizzatore"]}
    chatter = True
    tracked_fields = ["titolo", "inizio", "fine", "luogo"]
    buttons = ["scarica_ics", "invia_invito"]
    api = True

    def get_queryset(self, request):
        """Gli eventi privati li vedono solo organizzatore e partecipanti."""
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        visibili = qs.filter(Q(privato=False) | Q(organizzatore=user) | Q(partecipanti=user)).values("pk")
        return qs.filter(pk__in=visibili)

    def save_model(self, request, obj, form, change):
        if not change and obj.organizzatore_id is None:
            obj.organizzatore = request.user
        if change and obj.pk:
            precedente = Evento.objects.filter(pk=obj.pk).values_list("inizio", flat=True).first()
            if precedente != obj.inizio:
                obj.promemoria_inviato = False                  # spostato: il promemoria riparte
        super().save_model(request, obj, form, change)
        if not change:
            lavori.accoda("calendario.lavori.invia_inviti", evento_id=obj.pk)

    def scarica_ics(self, request, obj):
        risposta = HttpResponse(ics(obj), content_type="text/calendar; charset=utf-8")
        risposta["Content-Disposition"] = f'attachment; filename="evento-{obj.pk}.ics"'
        return risposta
    scarica_ics.short_description = "Scarica .ics"
    scarica_ics.ai = False
    scarica_ics.permission = "view"

    def invia_invito(self, request, obj):
        lavori.accoda("calendario.lavori.invia_inviti", evento_id=obj.pk)
        return "Inviti inviati ai partecipanti."
    invia_invito.short_description = "Invia di nuovo l'invito"
    invia_invito.rischio = "irreversibile"


@register
class TipoAppuntamentoView(ModelView):
    """I tipi di appuntamento prenotabili online: durata, operatori, orari della settimana."""
    model = TipoAppuntamento
    slug = "tipi-appuntamento"
    company_field = "azienda"
    list_display = ["nome", "codice", "durata", "attivo"]
    list_filter = ["attivo"]
    search_fields = ["nome", "codice"]
    form_layout = [("Appuntamento", [("nome", "codice"), ("durata", "pausa"), "luogo", "descrizione"]),
                   ("Prenotazione", ["operatori", ("preavviso", "giorni_avanti"), ("promemoria", "crea_opportunita"), "attivo"])]
    inlines = [Inline(OrarioAppuntamento, "tipo", ["giorno", "dalle", "alle"], titolo="Orari", extra=0)]
    buttons = ["apri_pagina"]

    def apri_pagina(self, request, obj):
        return redirect(reverse("calendario:prenota", args=[obj.codice]))
    apri_pagina.short_description = "Apri la pagina di prenotazione"
    apri_pagina.ai = False
    apri_pagina.permission = "view"


@register
class PrenotazioneView(ModelView):
    """Le prenotazioni arrivate dalla pagina pubblica."""
    model = Prenotazione
    slug = "prenotazioni"
    company_field = "azienda"
    list_display = ["inizio", "tipo", "nome", "email", "operatore", "stato"]
    list_filter = ["stato", "tipo", "operatore", "inizio"]
    search_fields = ["nome", "email", "societa", "telefono"]
    form_layout = [("Prenotazione", [("tipo", "stato"), ("inizio", "fine"), "operatore", "evento"]),
                   ("Cliente", [("nome", "email"), ("telefono", "societa"), "contatto", "note"])]
    readonly_fields = ["tipo", "stato", "inizio", "fine", "evento", "nome", "email", "contatto"]
    calendar_date = "inizio"
    list_group_by = ["tipo", "operatore", "inizio:mese"]
    graph = {"tipi": ["barre", "linee"], "misure": ["count"], "per": ["inizio:mese", "tipo", "operatore"]}
    chatter = True
    buttons = ["annulla"]

    def get_buttons(self, request, obj):
        return super().get_buttons(request, obj) if obj and obj.stato == Prenotazione.CONFERMATA else []

    def annulla(self, request, obj):
        prenotazioni.annulla(obj, da_cliente=False)
        return "Prenotazione annullata: il cliente riceve l'avviso."
    annulla.short_description = "Annulla e avvisa il cliente"
    annulla.rischio = "irreversibile"
