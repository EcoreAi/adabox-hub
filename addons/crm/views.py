from django.utils import timezone
from django.utils.html import format_html

from contatti.models import Contatto
from core.viste import ModelView, register

from .models import EtichettaCrm, FaseCrm, MotivoPerdita, Opportunita


@register
class OpportunitaView(ModelView):
    model = Opportunita
    slug = "opportunita"
    list_display = ["titolo", "cliente", "fase", "valore_atteso", "probabilita", "commerciale", "chiusura_prevista"]
    list_filter = ["stato", "fase", "commerciale", "etichette", "priorita", "chiusura_prevista"]
    search_fields = ["titolo", "nome_contatto", "email", "contatto__nome"]
    form_layout = [
        ("Opportunità", ["titolo", ("contatto", "commerciale"), ("valore_atteso", "probabilita"),
                         ("chiusura_prevista", "priorita"), ("fase", "stato"), "etichette"]),
        ("Lead", [("nome_contatto", "email", "telefono")]),
        ("Altro", ["note", "motivo_perdita", "@proprieta"]),
    ]
    company_field = "azienda"
    list_group_by = ["fase", "commerciale", "stato", "chiusura_prevista:mese"]
    list_sum = ["valore_atteso"]
    kanban_group = "fase"
    kanban_fields = ["valore_atteso", "contatto", "nome_contatto", "commerciale"]
    calendar_date = "chiusura_prevista"
    calendar_color = "stato"
    graph = {"tipi": ["barre", "torta", "linee"], "misure": ["sum:valore_atteso", "count"],
             "per": ["fase", "commerciale", "stato", "chiusura_prevista:mese"]}
    chatter = True
    tracked_fields = ["fase", "stato", "valore_atteso", "probabilita", "commerciale", "chiusura_prevista"]
    actions = ["assegna_a_me"]
    buttons = ["segna_vinta", "segna_persa", "riapri", "crea_contatto"]
    api = True

    def col_cliente(self, obj):
        return obj.contatto or obj.nome_contatto or "—"
    col_cliente.short_description = "Cliente"

    def col_valore_atteso(self, obj):
        return format_html("{} €", f"{obj.valore_atteso:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col_valore_atteso.short_description = "Valore atteso"

    def assegna_a_me(self, request, queryset):
        n = queryset.update(commerciale=request.user)
        return f"Opportunità assegnate a te: {n}."
    assegna_a_me.short_description = "Assegna a me"

    def _salva(self, request, obj):
        from core import chatter
        vecchi = chatter.valori(type(obj).objects.get(pk=obj.pk), self.tracked_fields)
        obj.save()
        chatter.traccia(obj, vecchi, request.user)

    def segna_vinta(self, request, obj):
        fase = FaseCrm.objects.filter(vinta=True).first()
        if fase is None:
            return "Nessuna fase di vittoria configurata."
        obj.fase = fase
        self._salva(request, obj)
        return f"«{obj}» vinta."
    segna_vinta.short_description = "Vinta"

    def segna_persa(self, request, obj):
        obj.stato, obj.probabilita, obj.chiusa_il = Opportunita.PERSA, 0, timezone.localdate()
        self._salva(request, obj)
        return f"«{obj}» persa. Indica il motivo nella scheda."
    segna_persa.short_description = "Persa"

    def riapri(self, request, obj):
        obj.stato, obj.chiusa_il, obj.motivo_perdita = Opportunita.APERTA, None, None
        if obj.fase.vinta:
            obj.fase = FaseCrm.objects.filter(vinta=False).order_by("-ordine").first() or obj.fase
        self._salva(request, obj)
        return f"«{obj}» riaperta."
    riapri.short_description = "Riapri"

    def crea_contatto(self, request, obj):
        if obj.contatto_id:
            return "L'opportunità ha già un contatto."
        if not obj.nome_contatto:
            return "Indica il nome del contatto del lead."
        obj.contatto = Contatto.objects.create(azienda=obj.azienda, nome=obj.nome_contatto, email=obj.email,
                                               telefono=obj.telefono, cliente=True)
        obj.save(update_fields=["contatto"])
        return f"Contatto «{obj.contatto}» creato e collegato."
    crea_contatto.short_description = "Crea contatto"


@register
class FaseView(ModelView):
    model = FaseCrm
    slug = "fasi"
    list_display = ["nome", "ordine", "probabilita", "vinta"]
    ordering = ["ordine"]


@register
class EtichettaView(ModelView):
    model = EtichettaCrm
    slug = "etichette"
    list_display = ["nome"]


@register
class MotivoPerditaView(ModelView):
    model = MotivoPerdita
    slug = "motivi"
    list_display = ["nome"]
