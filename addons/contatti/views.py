from django.utils import timezone

from core import chatter
from core.colori import iniziali, sicuro, tinta_persona
from core.viste import ModelView, register

from . import validatori, vies

from .models import Categoria, Contatto

COLORI_TIPO = {Contatto.AZIENDA: "azzurro", Contatto.PERSONA: "viola"}


def _ruolo(c):
    """(accento, icona, testo) del rapporto con il contatto: mai con il solo colore."""
    if not c.attivo:
        return "grigio", "icon-x", "Non attivo"
    if c.cliente and c.fornitore:
        return "viola", "icon-users", "Cliente e fornitore"
    if c.cliente:
        return "verde", "icon-check", "Cliente"
    if c.fornitore:
        return "azzurro", "icon-user", "Fornitore"
    return "grigio", "icon-user", "Nessun ruolo"


@register
class ContattoView(ModelView):
    model = Contatto
    slug = "contatti"
    list_display = ["nome", "codice", "tipo", "citta", "telefono", "email"]
    list_filter = ["tipo", "cliente", "fornitore", "categorie", "responsabile"]
    search_fields = ["nome", "codice", "email", "partita_iva", "codice_fiscale", "citta"]
    ordering = ["nome"]
    form_layout = [
        ("Anagrafica", ["tipo", "nome", ("societa", "ruolo"), ("cliente", "fornitore"), ("categorie", "responsabile")]),
        ("Recapiti", [("email", "pec"), ("telefono", "cellulare"), "sito", ("indirizzo", "cap"),
                      ("citta", "provincia", "nazione")]),
        ("Dati fiscali", [("partita_iva", "codice_fiscale", "codice_sdi"), "pubblica_amministrazione",
                          ("vies_valido", "vies_il")]),
        ("Altro", ["note", "attivo", "@proprieta"]),
    ]
    readonly_fields = ["codice", "vies_valido", "vies_il"]
    company_field = "azienda"
    sequence_field = ("codice", "contatti.contatto")
    list_group_by = ["tipo", "citta", "responsabile"]
    kanban_group = "tipo"
    kanban_fields = ["email", "telefono", "citta"]
    kanban_ricco = True
    chatter = True
    tracked_fields = ["nome", "email", "telefono", "cliente", "fornitore", "responsabile", "attivo"]
    import_key = "codice"
    reports = [{"nome": "Scheda contatto", "template": "contatti/report/contatto.html"}]
    actions = ["archivia"]
    buttons = ["verifica_vies"]
    api = True

    def get_buttons(self, request, obj):
        pulsanti = super().get_buttons(request, obj)
        return pulsanti if obj.partita_iva and obj.nazione in validatori.UE else [
            (n, e) for n, e in pulsanti if n != "verifica_vies"]

    def verifica_vies(self, request, obj):
        try:
            esito = vies.controlla(obj.nazione, obj.partita_iva)
        except vies.ViesNonDisponibile:
            return "Il VIES non risponde in questo momento: riprova più tardi."
        vecchi = chatter.valori(obj, ["vies_valido"])
        obj.vies_valido, obj.vies_il = esito["valido"], timezone.now()
        obj.save(update_fields=["vies_valido", "vies_il"])
        chatter.traccia(obj, vecchi, request.user)
        if not esito["valido"]:
            return f"{obj.nazione}{obj.partita_iva} non è attiva nel VIES: niente operazioni intracomunitarie senza IVA."
        return f"Partita IVA valida nel VIES{': ' + esito['nome'] if esito['nome'] else ''}."
    verifica_vies.short_description = "Verifica nel VIES"
    verifica_vies.ai = False
    verifica_vies.permission = "view"

    def archivia(self, request, queryset):
        n = queryset.update(attivo=False)
        return f"Contatti archiviati: {n}."
    archivia.short_description = "Archivia"

    def kanban_queryset(self, qs):
        return qs.select_related("societa", "responsabile").prefetch_related("categorie")

    def kanban_scheda(self, request, obj):
        accento, icona, testo = _ruolo(obj)
        scheda = {"accento": accento, "scadenza": {"icona": icona, "testo": testo},
                  "sottotitolo": " · ".join(p for p in (obj.ruolo, obj.citta) if p),
                  "righe": [p for p in (obj.email, obj.telefono or obj.cellulare) if p],
                  "etichette": [(c.nome, sicuro(c.colore)) for c in obj.categorie.all()]}
        if obj.responsabile_id:
            persona = obj.responsabile
            scheda["persona"] = {"iniziali": iniziali(persona), "nome": persona.get_full_name() or persona.get_username(),
                                 "tinta": tinta_persona(persona.pk)}
        return scheda

    def kanban_colonna(self, request, valore, qs):
        clienti, fornitori = qs.filter(cliente=True).count(), qs.filter(fornitore=True).count()
        return {"colore": COLORI_TIPO.get(valore, ""),
                "riepilogo": f"{clienti} {'cliente' if clienti == 1 else 'clienti'} · {fornitori} {'fornitore' if fornitori == 1 else 'fornitori'}"}


@register
class CategoriaView(ModelView):
    model = Categoria
    slug = "categorie"
    list_display = ["nome", "colore"]
    search_fields = ["nome"]
    api = True
