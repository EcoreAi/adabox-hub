"""I record nelle conversazioni: schede vive viste con i permessi di chi legge, condivisione, cronologia del record,
la conversazione dedicata a un record e il passaggio dal messaggio a un record nuovo."""
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone

from core import chatter
from core.generici import ct_di, modello_di
from core.models import Messaggio as MessaggioChatter
from core.registry import modules
from core.viste import registry

from . import servizi, testo
from .models import Canale, Collegamento, Iscrizione, Messaggio

MASSIMO_CAMPI = 4
MASSIMO_RECORD = 5
CHIAVE_SESSIONE = "discuss_crea_da"
VALIDITA_CREAZIONE = 3600                   # secondi
CAMPI_TITOLO = ("titolo", "oggetto", "nome", "riepilogo", "descrizione_breve")
CAMPI_TESTO = ("descrizione", "note", "nota", "corpo", "testo", "messaggio")


# --- dai link del testo ai record ---

def _record_del_percorso(percorso):
    """(modello, pk) se il percorso è il dettaglio di un record di una ModelView."""
    try:
        trovato = resolve(percorso)
    except Resolver404:
        return None
    pk = trovato.kwargs.get("pk")
    if pk is None or not (trovato.url_name or "").endswith("_dettaglio"):
        return None
    for nome in trovato.namespaces:
        for vista in registry.viste_di(nome):
            if vista.url("dettaglio", pk=pk) == percorso:
                return vista.model, pk
    return None


def riconosci(corpo, host=None):
    """I record citati con un link a questo stesso gestionale."""
    nostri = {urlsplit(settings.SITO_URL).netloc.lower()}
    if host:
        nostri.add(host.lower())
    trovati = []
    for url in testo.link_di(corpo):
        parti = urlsplit(url)
        if parti.netloc.lower() in nostri and (record := _record_del_percorso(parti.path)):
            trovati.append(record)
    return trovati


def _coppia(voce):
    """(content type, pk) da un record o da una coppia (modello, pk)."""
    if isinstance(voce, tuple):
        return ContentType.objects.get_for_model(voce[0]), voce[1]
    return ct_di(voce), voce.pk


def collega(messaggio, voci):
    """Lega i record al messaggio e lo annota nella cronologia di ciascuno."""
    for voce in voci[:MASSIMO_RECORD]:
        ct, pk = _coppia(voce)
        record = ct.model_class()._default_manager.filter(pk=pk).first()
        if record is None:
            continue
        _, nuovo = Collegamento.objects.get_or_create(messaggio=messaggio, content_type=ct, object_id=pk)
        if nuovo:
            _in_cronologia(record, messaggio)


def _in_cronologia(record, messaggio):
    """Il contesto arriva sul record. Di ciò che è privato si dice solo che c'è stato: chi vede il record non per
    questo può leggere la conversazione."""
    canale = messaggio.canale
    if canale.tipo == Canale.PUBBLICO:
        url = settings.SITO_URL + reverse("discuss:canale", args=[canale.pk]) + f"?a={messaggio.pk}"
        frase = f"Citato in #{canale.nome}"
        estratto = testo.piano(messaggio.corpo)[:200]
        corpo = f"{frase}: «{estratto}»\n{url}" if estratto else f"{frase}\n{url}"
    else:
        corpo = "Citato in una conversazione privata."
    chatter.scrivi(record, messaggio.autore, corpo, tipo=MessaggioChatter.SISTEMA)


# --- la scheda: si calcola a ogni lettura, con i permessi di chi legge ---

def scheda(request, ct_id, pk):
    """Ciò che chi legge può sapere del record. Senza accesso non esce nemmeno il titolo."""
    base = {"ct": ct_id, "pk": pk, "url_scheda": reverse("discuss:scheda", args=[ct_id, pk])}
    modello = modello_di(ct_id)
    vista = registry.per_modello(modello) if modello else None
    if vista is None:
        return {**base, "stato": "assente"}
    if vista.modulo in modules.disattivati():
        return {**base, "stato": "spento"}
    try:
        obj = vista.get_object(request, pk)
    except Http404:
        # sparito o fuori dall'azienda di chi legge: dall'esterno i due casi non si distinguono
        return {**base, "stato": "vietato" if modello._default_manager.filter(pk=pk).exists() else "assente"}
    if not vista.has_view_permission(request, obj):
        return {**base, "stato": "vietato"}
    titolo, campi = str(obj), []
    for c in [c for c in vista.list_display if c != "__str__"]:
        try:
            valore = vista.col_valore(request, obj, c)
            etichetta = vista.etichette.get(c) or vista.etichetta(c)
        except (PermissionDenied, AttributeError, ValueError, KeyError, TypeError):
            continue
        if str(valore) not in ("", "None", chatter.VUOTO, titolo):      # né vuoti né il titolo ripetuto
            campi.append({"etichetta": etichetta, "valore": valore})
        if len(campi) == MASSIMO_CAMPI:
            break
    puo_modificare = vista.has_change_permission(request, obj)
    return {**base, "stato": "ok", "titolo": titolo, "tipo": str(vista.opts.verbose_name).capitalize(), "campi": campi,
            "url": vista.url("dettaglio", pk=obj.pk), "url_modifica": vista.url("modifica", pk=obj.pk) if puo_modificare else "",
            "segue": chatter.segue(obj, request.user), "ha_chatter": bool(vista.chatter),
            "bottoni": [(e, vista.url("bottone", pk=obj.pk, nome=n)) for n, e in vista.get_buttons(request, obj)] if puo_modificare else []}


def arricchisci(request, elenco):
    """Le schede di ogni messaggio, con una lettura sola per ciascun record anche se è citato più volte."""
    for m in elenco:
        m.schede = []
    per_messaggio = {m.pk: m for m in elenco}
    gia = {}
    for c in Collegamento.objects.filter(messaggio_id__in=per_messaggio).order_by("pk"):
        chiave = (c.content_type_id, c.object_id)
        if chiave not in gia:
            gia[chiave] = scheda(request, *chiave)
        per_messaggio[c.messaggio_id].schede.append(gia[chiave])
    return elenco


def record_di(request, messaggio):
    """I record del messaggio che chi legge può vedere, per scegliere dove creare un'attività."""
    return [s for c in messaggio.collegamenti.all() if (s := scheda(request, c.content_type_id, c.object_id))["stato"] == "ok"]


# --- condividere ---

def _puo_vedere(utente, obj):
    return utente.has_perm(f"{obj._meta.app_label}.view_{obj._meta.model_name}")


@transaction.atomic
def condividi(obj, autore, messaggio, persone, canali):
    """Un messaggio con la scheda in ogni canale e in ogni messaggio diretto. Dice chi non vedrà i dati."""
    senza_accesso = []
    for persona in persone:
        servizi.invia(servizi.diretto([autore, persona]), autore, messaggio, record=[obj])
        if not _puo_vedere(persona, obj):
            senza_accesso.append(servizi.nome_di(persona))
    for canale in canali:
        servizi.invia(canale, autore, messaggio, record=[obj])
    return senza_accesso


@transaction.atomic
def canale_del_record(obj, utente):
    """La conversazione dedicata al record: la prima volta nasce con i follower e la scheda fissata in cima."""
    ct = ct_di(obj)
    canale = Canale.objects.filter(record_ct=ct, record_id=obj.pk, archiviato=False).first()
    if canale is not None:
        servizi.entra(canale, utente)
        return canale
    canale = Canale.objects.create(nome=str(obj)[:80], tipo=Canale.PRIVATO, creato_da=utente, record_ct=ct, record_id=obj.pk,
                                   descrizione=f"Conversazione su {obj._meta.verbose_name} «{obj}»"[:250])
    servizi.iscrivi(canale, utente, 0, ruolo=Iscrizione.AMMINISTRATORE)
    for u in chatter.follower_di(obj):
        if u.pk != utente.pk and u.is_active and u.has_perm("discuss.view_canale") and _puo_vedere(u, obj):
            servizi.iscrivi(canale, u, 0)
    primo = servizi.invia(canale, utente, "", record=[obj])
    servizi.fissa(primo, utente)
    return canale


# --- dal messaggio a un record nuovo ---

def creabili(request):
    """[(modulo, [(valore, etichetta)])]: ciò che la persona può creare e che ha un campo per il titolo."""
    spenti = modules.disattivati()
    gruppi = []
    for slug in sorted(settings.ADDONS_ATTIVI):
        if slug in spenti or slug == "discuss":
            continue
        voci = []
        for vista in registry.viste_di(slug):
            if vista.has_add_permission(request) and _campo(vista, request, CAMPI_TITOLO):
                voci.append((f"{slug}:{vista.slug}", str(vista.opts.verbose_name).capitalize()))
        if voci:
            gruppi.append((slug.capitalize(), sorted(voci, key=lambda v: v[1])))
    return gruppi


def _campo(vista, request, nomi):
    campi = vista.get_form_class(request).base_fields
    return next((n for n in nomi if n in campi), None)


def vista_creabile(request, valore):
    slug, _, nome = valore.partition(":")
    if slug in modules.disattivati():
        return None
    for vista in registry.viste_di(slug):
        if vista.slug == nome and vista.has_add_permission(request) and _campo(vista, request, CAMPI_TITOLO):
            return vista
    return None


def iniziali(vista, request, messaggio):
    """I valori con cui si apre il modulo: la prima riga come titolo, il testo con il link alla conversazione."""
    piano = testo.piano(messaggio.corpo)
    valori = {_campo(vista, request, CAMPI_TITOLO): piano[:120] or "Da una conversazione"}
    if campo_testo := _campo(vista, request, CAMPI_TESTO):
        if campo_testo not in valori:
            link = settings.SITO_URL + reverse("discuss:canale", args=[messaggio.canale_id]) + f"?a={messaggio.pk}"
            valori[campo_testo] = f"{messaggio.corpo}\n\nDa una conversazione: {link}"
    return valori


def lega_creato(request, obj):
    """Sulla pagina del record appena salvato: lo lega al messaggio da cui è nato e lo dice nella conversazione.
    Vale una volta sola e solo per un record più recente di quando si è aperto il modulo."""
    pendente = request.session.get(CHIAVE_SESSIONE)
    if not pendente or pendente["ct"] != ct_di(obj).pk or obj.pk <= pendente["dopo"]:
        return
    del request.session[CHIAVE_SESSIONE]
    if timezone.now().timestamp() - pendente["quando"] > VALIDITA_CREAZIONE:
        return
    messaggio = Messaggio.objects.filter(pk=pendente["m"]).select_related("canale").first()
    if messaggio is None or not servizi.puo_vedere(request.user, messaggio.canale):
        return
    collega(messaggio, [obj])
    servizi.avviso(messaggio.canale, request.user, f"{servizi.nome_di(request.user)} ha creato «{obj}» da un messaggio")
    from . import eventi
    eventi.emetti("agg", messaggio.canale, m=messaggio.pk)
