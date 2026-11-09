import datetime

from django.db.models import DecimalField, ExpressionWrapper, F, Sum
from django.utils import timezone
from django.utils.html import format_html

from contatti.models import Contatto
from core.colori import iniziali, tinta_persona
from core.viste import ModelView, register

from .models import EtichettaCrm, FaseCrm, ModuloWeb, MotivoPerdita, Opportunita, ObiettivoVendita, TeamVendita

GIORNI_URGENZA = 7


def _euro_tondi(valore):
    return f"{valore:,.0f} €".replace(",", ".")


def _scadenza(o, oggi):
    """(accento, icona, testo): lo stato della trattativa a colpo d'occhio, mai con il solo colore."""
    if o.stato == Opportunita.VINTA:
        return "verde", "icon-check", f"Vinta il {o.chiusa_il:%d/%m/%Y}" if o.chiusa_il else "Vinta"
    if o.stato == Opportunita.PERSA:
        return "grigio", "icon-x", f"Persa il {o.chiusa_il:%d/%m/%Y}" if o.chiusa_il else "Persa"
    if o.chiusura_prevista is None:
        return "grigio", "icon-calendar", "Senza data di chiusura"
    if o.chiusura_prevista < oggi:
        return "rosso", "icon-alert-triangle", f"Scaduta il {o.chiusura_prevista:%d/%m/%Y}"
    if o.chiusura_prevista == oggi:
        return "arancio", "icon-alert-triangle", "Si chiude oggi"
    if o.chiusura_prevista <= oggi + datetime.timedelta(days=GIORNI_URGENZA):
        return "arancio", "icon-alert-triangle", f"Si chiude il {o.chiusura_prevista:%d/%m/%Y}"
    return "verde", "icon-calendar", f"Si chiude il {o.chiusura_prevista:%d/%m/%Y}"


@register
class OpportunitaView(ModelView):
    model = Opportunita
    slug = "opportunita"
    list_display = ["titolo", "cliente", "fase", "valore_atteso", "probabilita", "punteggio", "commerciale", "chiusura_prevista"]
    list_filter = ["stato", "fase", "commerciale", "etichette", "priorita", "chiusura_prevista"]
    search_fields = ["titolo", "nome_contatto", "email", "contatto__nome"]
    form_layout = [
        ("Opportunità", ["titolo", ("contatto", "commerciale"), ("valore_atteso", "probabilita"),
                         ("chiusura_prevista", "priorita"), ("fase", "stato"), "etichette"]),
        ("Lead", [("nome_contatto", "email", "telefono")]),
        ("Altro", ["note", "origine", "motivo_perdita", "@proprieta"]),
    ]
    company_field = "azienda"
    list_group_by = ["fase", "commerciale", "stato", "origine", "chiusura_prevista:mese"]
    list_sum = ["valore_atteso"]
    kanban_group = "fase"
    kanban_fields = ["valore_atteso", "contatto", "nome_contatto", "commerciale"]
    kanban_ricco = True
    kanban_ordini = [("-valore_atteso", "Valore"), ("chiusura_prevista", "Chiusura prevista"), ("-punteggio", "Punteggio")]
    kanban_ordine_chiuse = "-chiusa_il"
    calendar_date = "chiusura_prevista"
    calendar_color = "stato"
    graph = {"tipi": ["barre", "torta", "linee"], "misure": ["sum:valore_atteso", "count"],
             "per": ["fase", "commerciale", "stato", "chiusura_prevista:mese"]}
    chatter = True
    tracked_fields = ["fase", "stato", "valore_atteso", "probabilita", "commerciale", "chiusura_prevista"]
    actions = ["assegna_a_me", "riassegna_nel_team"]
    buttons = ["segna_vinta", "segna_persa", "riapri", "crea_contatto", "ricalcola_punteggio"]
    api = True

    def col_cliente(self, obj):
        return obj.contatto or obj.nome_contatto or "—"
    col_cliente.short_description = "Cliente"

    def col_valore_atteso(self, obj):
        return format_html("{} €", f"{obj.valore_atteso:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col_valore_atteso.short_description = "Valore atteso"

    def kanban_queryset(self, qs):
        return qs.select_related("contatto", "commerciale").prefetch_related("etichette")

    def kanban_scheda(self, request, obj):
        accento, icona, testo = _scadenza(obj, timezone.localdate())
        scheda = {"accento": accento, "scadenza": {"icona": icona, "testo": testo}, "sottotitolo": self.col_cliente(obj),
                  "valore": self.col_valore_atteso(obj), "etichette": [(e.nome, e.colore) for e in obj.etichette.all()],
                  "barra": (obj.probabilita, f"Probabilità {obj.probabilita}%")}
        if obj.punteggio is not None and obj.stato == Opportunita.APERTA:
            colore = "verde" if obj.punteggio >= 60 else "azzurro" if obj.punteggio >= 30 else "grigio"
            scheda["etichette"] = [(f"Punteggio {obj.punteggio}", colore)] + scheda["etichette"]
        if obj.priorita:
            scheda["stelle"] = (range(obj.priorita), range(3 - obj.priorita), obj.get_priorita_display())
        if obj.commerciale_id:
            persona = obj.commerciale
            scheda["persona"] = {"iniziali": iniziali(persona), "nome": persona.get_full_name() or persona.get_username(),
                                 "tinta": tinta_persona(persona.pk)}
        return scheda

    def kanban_colonna(self, request, valore, qs):
        """Le trattative perse restano visibili nella colonna, ma non contano nei totali."""
        ponderato = ExpressionWrapper(F("valore_atteso") * F("probabilita") / 100, output_field=DecimalField(max_digits=14, decimal_places=2))
        somme = qs.exclude(stato=Opportunita.PERSA).aggregate(totale=Sum("valore_atteso"), ponderato=Sum(ponderato))
        fase = FaseCrm.objects.filter(pk=valore).first() if valore else None
        return {"colore": fase.colore if fase else "",
                "riepilogo": f"{_euro_tondi(somme['totale'] or 0)} · ponderato {_euro_tondi(somme['ponderato'] or 0)}"}

    def assegna_a_me(self, request, queryset):
        n = queryset.update(commerciale=request.user)
        return f"Opportunità assegnate a te: {n}."
    assegna_a_me.short_description = "Assegna a me"

    def riassegna_nel_team(self, request, queryset):
        """Al team del primo responsabile o membro che è l'utente; altrimenti al primo team attivo."""
        from .models import TeamVendita
        from .risultati import riassegna_nel_team
        team = (TeamVendita.objects.filter(azienda=request.azienda, responsabile=request.user, attivo=True).first()
                or TeamVendita.objects.filter(azienda=request.azienda, membri=request.user, attivo=True).first()
                or TeamVendita.objects.filter(azienda=request.azienda, attivo=True).first())
        if team is None:
            return "Nessun team di vendita: crealo prima."
        dati = riassegna_nel_team(list(queryset.filter(stato=Opportunita.APERTA)), team)
        return f"Riassegnate nel team {team}: " + (", ".join(f"{u.get_full_name() or u.username} {n}" for u, n in dati.items()) or "nessuna") + "."
    riassegna_nel_team.short_description = "Riassegna nel team (a chi ha meno lavoro)"

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

    def ricalcola_punteggio(self, request, obj):
        from . import punteggio
        punteggio.ricalcola(obj.azienda_id)
        obj.refresh_from_db()
        return f"Punteggio ricalcolato: {obj.punteggio}." if obj.punteggio is not None else "Storico insufficiente per il punteggio."
    ricalcola_punteggio.short_description = "Ricalcola il punteggio"
    ricalcola_punteggio.permission = "view"

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
    list_display = ["nome", "colore", "ordine", "probabilita", "vinta"]
    ordering = ["ordine"]


@register
class EtichettaView(ModelView):
    model = EtichettaCrm
    slug = "etichette"
    list_display = ["nome", "colore"]


@register
class MotivoPerditaView(ModelView):
    model = MotivoPerdita
    slug = "motivi"
    list_display = ["nome"]


@register
class ModuloWebView(ModelView):
    """I moduli «contattaci» da mettere sul sito: nel dettaglio il codice da incollare nella pagina."""
    model = ModuloWeb
    slug = "moduli"
    list_display = ["nome", "commerciale", "etichetta", "attivo"]
    search_fields = ["nome", "domini"]
    form_layout = [("Modulo", [("nome", "attivo"), "domini", ("chiedi_telefono", "chiedi_azienda")]),
                   ("Chi lo riceve", [("commerciale", "etichetta")]),
                   ("Testi", ["grazie", "privacy_url"])]
    company_field = "azienda"


@register
class TeamVenditaView(ModelView):
    model = TeamVendita
    slug = "team"
    company_field = "azienda"
    list_display = ["nome", "responsabile", "attivo"]
    form_layout = [("Team", [("nome", "responsabile"), "membri", "attivo"])]
    ai_descrizione = "I team di vendita con responsabile e membri."


@register
class ObiettivoVenditaView(ModelView):
    model = ObiettivoVendita
    slug = "obiettivi"
    company_field = "azienda"
    list_display = ["utente", "team", "dal", "al", "importo", "numero"]
    list_filter = ["team", "utente"]
    form_layout = [("Obiettivo", [("utente", "team"), ("dal", "al"), ("importo", "numero")])]
    ai_descrizione = "Gli obiettivi di vendita per persona o team e periodo."
