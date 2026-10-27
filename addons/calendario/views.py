from django.db.models import Q
from django.http import HttpResponse

from core import lavori
from core.viste import ModelView, register

from .ics import ics
from .models import Evento


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
    scarica_ics.permission = "view"

    def invia_invito(self, request, obj):
        lavori.accoda("calendario.lavori.invia_inviti", evento_id=obj.pk)
        return "Inviti inviati ai partecipanti."
    invia_invito.short_description = "Invia di nuovo l'invito"
