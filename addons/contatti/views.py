from django.utils import timezone

from core import chatter
from core.colori import iniziali, sicuro, tinta_persona
from core.viste import ModelView, register

from . import validatori, vies

from .models import Categoria, Contatto, IndirizzoContatto, Segmento

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
    list_filter = ["tipo", "cliente", "fornitore", "categorie", "responsabile", "segmenti", "classe_abc"]
    search_fields = ["nome", "codice", "email", "partita_iva", "codice_fiscale", "citta"]
    ordering = ["nome"]
    form_layout = [
        ("Anagrafica", ["tipo", "nome", ("societa", "ruolo"), ("cliente", "fornitore"), ("categorie", "responsabile")]),
        ("Recapiti", [("email", "pec"), ("telefono", "cellulare"), "sito", ("indirizzo", "cap"),
                      ("citta", "provincia", "nazione")]),
        ("Dati fiscali", [("partita_iva", "codice_fiscale", "codice_sdi"), "pubblica_amministrazione",
                          ("vies_valido", "vies_il")]),
        ("Fido", [("fido", "fido_blocca")]),
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


@register
class IndirizzoView(ModelView):
    """Indirizzi in più dei contatti: consegna, fatturazione, sedi operative. Si aggiungono dalla scheda del contatto."""
    model = IndirizzoContatto
    slug = "indirizzi"
    list_display = ["contatto", "tipo", "nome", "indirizzo", "citta", "predefinito"]
    list_filter = ["tipo", "contatto"]
    search_fields = ["contatto__nome", "nome", "indirizzo", "citta"]
    form_layout = [("Indirizzo", [("contatto", "tipo"), ("nome", "presso"), "indirizzo", ("cap", "citta"), ("provincia", "nazione"),
                                  "predefinito"])]
    company_field = "azienda"
    ai_descrizione = "Gli indirizzi di consegna, fatturazione e delle sedi operative dei contatti."


@register
class SegmentoView(ModelView):
    """Liste di contatti con regole salvate: si ricalcolano ogni notte o con il bottone."""
    model = Segmento
    slug = "segmenti"
    company_field = "azienda"
    list_display = ["nome", "numero", "ricalcolato_il", "attivo"]
    list_filter = ["attivo"]
    search_fields = ["nome", "descrizione"]
    form_layout = [("Segmento", [("nome", "attivo"), "descrizione"]),
                   ("Chi", [("solo_clienti", "solo_fornitori"), ("tipo", "responsabile"), "categorie", ("province", "nazione")]),
                   ("Fatturato e acquisti", [("classi", "fatturato_minimo", "fatturato_massimo"), ("acquisto_entro", "inattivo_da")]),
                   ("A mano", ["aggiunti", "esclusi"])]
    buttons = ["ricalcola", "apri_contatti"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)          # salva anche categorie, aggiunti ed esclusi
        from . import segmenti
        segmenti.ricalcola_segmento(obj)

    def ricalcola(self, request, obj):
        from . import segmenti
        if segmenti._fatture(obj.azienda_id) is not None:
            segmenti.classi_abc(obj.azienda_id)
        return f"Segmento ricalcolato: {segmenti.ricalcola_segmento(obj)} contatti."
    ricalcola.short_description = "Ricalcola"
    ricalcola.permission = "view"

    def apri_contatti(self, request, obj):
        from django.shortcuts import redirect
        from django.urls import reverse
        return redirect(reverse("contatti:contatti_lista") + f"?f_segmenti={obj.pk}")
    apri_contatti.short_description = "Vedi i contatti"
    apri_contatti.permission = "view"
    apri_contatti.ai = False
