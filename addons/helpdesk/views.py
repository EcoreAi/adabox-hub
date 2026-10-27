from django.utils import timezone
from django.utils.html import format_html

from core import chatter
from core.viste import ModelView, register

from .email import segui_team
from .models import FaseTicket, Team, Ticket


@register
class TicketView(ModelView):
    model = Ticket
    slug = "ticket"
    list_display = ["oggetto", "numero", "cliente", "priorita", "fase", "assegnatario", "sla"]
    list_filter = ["fase", "priorita", "team", "assegnatario"]
    search_fields = ["oggetto", "numero", "email_cliente", "contatto__nome", "descrizione"]
    form_layout = [
        ("Richiesta", ["oggetto", ("contatto", "email_cliente"), "descrizione"]),
        ("Gestione", [("team", "assegnatario"), ("priorita", "fase"), "@proprieta"]),
    ]
    readonly_fields = ["numero", "creato", "scadenza_sla", "chiuso_il"]
    company_field = "azienda"
    list_group_by = ["fase", "priorita", "team", "assegnatario", "creato:mese"]
    kanban_group = "fase"
    kanban_fields = ["numero", "priorita", "assegnatario", "sla"]
    graph = {"tipi": ["barre", "torta", "linee"], "misure": ["count"],
             "per": ["fase", "priorita", "team", "assegnatario", "creato:mese"]}
    chatter = True
    tracked_fields = ["fase", "priorita", "assegnatario", "team"]
    actions = ["assegna_a_me"]
    buttons = ["prendi_in_carico", "risolvi"]
    api = True

    def destinatari_esterni(self, obj):
        return [obj.email_cliente] if obj.email_cliente else []

    def save_model(self, request, obj, form, change):
        if not change and not obj.email_cliente and obj.contatto_id and obj.contatto.email:
            obj.email_cliente = obj.contatto.email
        super().save_model(request, obj, form, change)
        if not change:
            segui_team(obj)

    def col_cliente(self, obj):
        return obj.contatto or obj.email_cliente or "—"
    col_cliente.short_description = "Cliente"

    def col_sla(self, obj):
        if obj.fase.chiusa:
            return format_html('<span class="ui-pill ui-pill-neutral">{}</span>', "chiuso")
        if obj.scadenza_sla is None:
            return "—"
        resto = obj.scadenza_sla - timezone.now()
        if resto.total_seconds() <= 0:
            return format_html('<span class="ui-pill ui-pill-danger">{}</span>', "scaduto")
        classe = "ui-pill-warn" if resto.total_seconds() < 7200 else "ui-pill-ok"
        return format_html('<span class="ui-pill {}">{}</span>', classe, timezone.localtime(obj.scadenza_sla).strftime("%d/%m %H:%M"))
    col_sla.short_description = "SLA"

    def _salva(self, request, obj):
        vecchi = chatter.valori(Ticket.objects.get(pk=obj.pk), self.tracked_fields)
        obj.save()
        chatter.traccia(obj, vecchi, request.user)

    def assegna_a_me(self, request, queryset):
        for t in queryset:
            t.assegnatario = request.user
            self._salva(request, t)
        return "Ticket assegnati a te."
    assegna_a_me.short_description = "Assegna a me"

    def prendi_in_carico(self, request, obj):
        obj.assegnatario = request.user
        fasi = list(FaseTicket.objects.filter(chiusa=False))
        if fasi and obj.fase_id == fasi[0].pk and len(fasi) > 1:
            obj.fase = fasi[1]                             # da "nuovo" alla fase di lavorazione
        self._salva(request, obj)
        chatter.segui(obj, request.user)
        return f"{obj} preso in carico."
    prendi_in_carico.short_description = "Prendi in carico"

    def risolvi(self, request, obj):
        fase = FaseTicket.objects.filter(chiusa=True).first()
        if fase is None:
            return "Nessuna fase di chiusura configurata."
        obj.fase = fase
        self._salva(request, obj)
        return f"{obj} risolto."
    risolvi.short_description = "Risolvi"


@register
class TeamView(ModelView):
    model = Team
    slug = "team"
    list_display = ["nome"]


@register
class FaseTicketView(ModelView):
    model = FaseTicket
    slug = "fasi"
    list_display = ["nome", "ordine", "chiusa"]
