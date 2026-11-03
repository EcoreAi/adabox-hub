from django.db.models import Avg, Count
from django.utils import timezone
from django.utils.html import format_html

from core import chatter
from core.viste import ModelView, register, schede

from .email import segui_team
from .models import Articolo, CategoriaArticolo, FaseTicket, Team, Ticket, Valutazione


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
    kanban_ricco = True
    graph = {"tipi": ["barre", "torta", "linee"], "misure": ["count"],
             "per": ["fase", "priorita", "team", "assegnatario", "creato:mese"]}
    chatter = True
    tracked_fields = ["fase", "priorita", "assegnatario", "team"]
    actions = ["assegna_a_me"]
    buttons = ["prendi_in_carico", "risolvi"]
    api = True


    def kanban_queryset(self, qs):
        return qs.select_related("contatto", "assegnatario", "fase")

    def _esito_sla(self, obj):
        if obj.fase.chiusa:
            return (*schede.FATTO, "Chiuso")
        if obj.scadenza_sla is None:
            return "grigio", "icon-calendar", "Senza SLA"
        ora = timezone.localtime(obj.scadenza_sla)
        resto = (obj.scadenza_sla - timezone.now()).total_seconds()
        if resto <= 0:
            return "rosso", "icon-alert-triangle", f"SLA scaduto il {ora:%d/%m %H:%M}"
        return ("arancio", "icon-alert-triangle", f"SLA entro le {ora:%H:%M}") if resto < 7200 else ("verde", "icon-calendar", f"SLA entro il {ora:%d/%m %H:%M}")

    def kanban_scheda(self, request, obj):
        return schede.scheda(self._esito_sla(obj), sottotitolo=" · ".join(str(p) for p in (obj.numero, self.col_cliente(obj)) if p and p != "—"),
                             stelle=schede.stelle({Ticket.MEDIA: 1, Ticket.ALTA: 2, Ticket.URGENTE: 3}.get(obj.priorita, 0), obj.get_priorita_display()),
                             persona=schede.persona(obj.assegnatario))

    def kanban_colonna(self, request, valore, qs):
        return {"colore": "verde"} if FaseTicket.objects.filter(pk=valore, chiusa=True).exists() else {}

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
    list_display = ["nome", "gradimento"]

    def col_gradimento(self, obj):
        dati = Valutazione.objects.filter(ticket__team=obj).aggregate(m=Avg("voto"), n=Count("pk"))
        return f"{dati['m']:.1f} ★ su {dati['n']} valutazioni" if dati["n"] else "—"
    col_gradimento.short_description = "Gradimento dei clienti"


@register
class FaseTicketView(ModelView):
    model = FaseTicket
    slug = "fasi"
    list_display = ["nome", "ordine", "chiusa"]


@register
class ValutazioneView(ModelView):
    model = Valutazione
    slug = "valutazioni"
    list_display = ["creata", "ticket", "stelle", "commento"]
    list_filter = ["voto", "ticket__team", "creata"]
    search_fields = ["ticket__numero", "ticket__oggetto", "commento"]
    readonly_fields = ["ticket", "voto", "commento", "creata"]
    form_layout = [("Valutazione", ["ticket", "voto", "commento", "creata"])]
    ordering = ["-creata"]
    list_group_by = ["voto", "ticket__team", "creata:mese"]
    graph = {"tipi": ["barre", "torta"], "misure": ["count"], "per": ["voto", "ticket__team", "creata:mese"]}

    def col_stelle(self, obj):
        return format_html('<span class="hd-stelle" aria-label="{} su 5">{}</span>', obj.voto, obj.stelle)
    col_stelle.short_description = "Voto"

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("ticket")
        azienda_id = getattr(getattr(request, "azienda", None), "pk", None)
        return qs.filter(ticket__azienda_id=azienda_id) if azienda_id is not None else qs

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@register
class ArticoloView(ModelView):
    model = Articolo
    slug = "articoli"
    list_display = ["titolo", "categoria", "stato", "visite", "utilita", "aggiornato"]
    list_filter = ["pubblicato", "pubblico", "categoria"]
    search_fields = ["titolo", "corpo"]
    form_layout = [("Articolo", ["titolo", "categoria", "corpo"]), ("Pubblicazione", [("pubblicato", "pubblico")])]
    readonly_fields = ["visite", "utile_si", "utile_no", "aggiornato"]
    company_field = "azienda"
    list_group_by = ["categoria", "pubblicato"]
    import_key = "titolo"
    actions = ["pubblica"]

    def col_stato(self, obj):
        if not obj.pubblicato:
            return format_html('<span class="ui-pill ui-pill-neutral">Bozza</span>')
        return format_html('<span class="ui-pill {}">{}</span>', "ui-pill-ok" if obj.pubblico else "ui-pill-info",
                           "Online" if obj.pubblico else "Solo clienti")
    col_stato.short_description = "Stato"

    def col_utilita(self, obj):
        voti = obj.utile_si + obj.utile_no
        return f"{obj.utile_si * 100 // voti}% su {voti}" if voti else "—"
    col_utilita.short_description = "Utile"

    def save_model(self, request, obj, form, change):
        if not change:
            obj.autore = request.user
        super().save_model(request, obj, form, change)

    def pubblica(self, request, queryset):
        return f"Articoli pubblicati: {queryset.update(pubblicato=True)}."
    pubblica.short_description = "Pubblica per i clienti"


@register
class CategoriaArticoloView(ModelView):
    model = CategoriaArticolo
    slug = "categorie-guida"
    list_display = ["nome", "descrizione", "ordine"]
