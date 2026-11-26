"""Le previsioni pronte: quelle che il cliente trova già fatte per le app che ha, senza niente da scrivere.

Ognuna è dichiarata nel registro (`registra`) con titolo, app, permesso, la funzione che costruisce la specifica per
l'azienda e i campi della vista di origine che usa. Il lavoro della notte e «Aggiorna» le calcolano con l'accesso
all'intera azienda e le salvano in `PrevisionePronta` (calcolo.py). Le salvate le vede solo chi vede tutta la vista
di origine: per chi ha regole di riga, campi nascosti o righe tolte dai filtri dei moduli lì si calcolano al momento
con i suoi permessi, con una cache breve (spec, «4 quater. Permessi»). Nella prima versione ci sono qui quelle di
Vendite (spec, «4 ter»)."""
import logging
from dataclasses import dataclass
from typing import Callable

from django.apps import apps
from django.core.cache import cache
from django.utils import timezone

from core import regole
from core.models import RegolaRiga
from core.registry import modules
from core.viste import interroga, registry
from core.viste.interroga import ErroreInterrogazione

from . import motore, servizio
from .models import PrevisionePronta
from .servizio import ErrorePrevisione

log = logging.getLogger("previsioni.pronte")

CACHE_SECONDI = 600                 # le calcolate al momento e il confronto dei filtri, per utente e azienda
CACHE_ERRORE = 60                   # un calcolo al momento fallito: il servizio non si richiama a ogni pagina (Ruling 27)
NON_DISPONIBILE = "Previsione non disponibile per te in questa azienda."
NON_CALCOLATA = "Previsione non ancora calcolata: si calcola stanotte, o subito con «Aggiorna»."


@dataclass(frozen=True)
class Pronta:
    chiave: str
    titolo: str | Callable                       # testo, o funzione(azienda) -> testo
    app: str
    permesso: str
    spec: Callable                               # funzione(azienda) -> specifica del motore
    campi: tuple                                 # i campi delle viste di origine che la previsione usa
    aggiunte: Callable | None = None             # funzione(request) -> dict aggiunto al risultato del motore

    def titolo_per(self, azienda):
        return self.titolo(azienda) if callable(self.titolo) else self.titolo


_registro: dict[str, Pronta] = {}


def registra(chiave, titolo, app, permesso, spec, campi, aggiunte=None):
    _registro[chiave] = Pronta(chiave, titolo, app, permesso, spec, tuple(campi), aggiunte)
    return _registro[chiave]


def di_app(app):
    return [p for p in _registro.values() if p.app == app]


def app_attiva(slug, azienda, user=None):
    """L'app è installata, accesa, in licenza e vale per l'azienda (non riservata ad altre: Modulo.aziende). Per
    Previsioni è il controllo di tutto il modulo (`servizio.abilitato`)."""
    if slug == "previsioni":
        return servizio.abilitato(azienda, user)
    return (apps.is_installed(slug) and slug not in modules.disattivati()
            and modules.per_azienda(slug, azienda, user))


def calcola(spec, request):
    """La previsione della specifica con i permessi della richiesta: per gruppo se c'è «raggruppa»."""
    if spec.get("raggruppa"):
        return motore.calcola_per_gruppo(spec, request)
    return motore.calcola_previsione(spec, request)


def calcola_pronta(pronta, spec, request):
    """La previsione pronta con i permessi della richiesta, con le sue aggiunte (es. le righe escluse)."""
    risultato = calcola(spec, request)
    if pronta.aggiunte is not None:
        risultato.update(pronta.aggiunte(request))
    return risultato


def viste_di(spec):
    """Le viste di origine («modulo.slug») di una specifica: quelle delle componenti della misura aziendale, o la
    vista. ErroreInterrogazione se la misura non c'è (app spenta)."""
    if spec.get("misura_aziendale"):
        from core import misure
        return sorted({c.vista for c in misure.per_nome(spec["misura_aziendale"]).componenti})
    return [spec["vista"]]


def _vista(vista_id):
    """La ModelView registrata «modulo.slug», o None (anche se il modulo non è installato)."""
    modulo, _, slug = vista_id.partition(".")
    if not apps.is_installed(modulo):
        return None
    registry.autodiscover([modulo])
    return next((v for v in registry.viste_di(modulo) if v.slug == slug), None)


def limitato(request, vista_id, campi):
    """True se l'utente non vede tutta la vista `vista_id`: non è superuser e il suo ruolo ha regole di riga su quella
    vista, o uno dei `campi` è nascosto per lui, o i filtri dei moduli gli tolgono qualche riga. Allora le previsioni
    salvate, calcolate sull'intera azienda, non fanno per lui."""
    if request.user.is_superuser:
        return False
    ruolo = regole.ruolo_di(request)
    if ruolo is not None:
        if RegolaRiga.objects.filter(vista=vista_id, ruolo_id=ruolo, attiva=True).exists():
            return True
        vista = _vista(vista_id)
        if vista is None or set(campi) & regole.nascosti(vista, request):
            return True
    return _filtrata(request, vista_id)


def _filtrata(request, vista_id):
    """True se i filtri dei moduli (core.regole.registra_filtro, applicati come fa applica_righe) tolgono all'utente
    qualche riga della vista nell'azienda: si contano le righe con e senza. Un filtro rotto conta come filtrata.
    In cache per CACHE_SECONDI, per utente, azienda e vista."""
    filtri = list(regole._FILTRI)
    if not filtri:
        return False
    chiave = f"previsioni:filtrata:{request.user.pk}:{getattr(request.azienda, 'pk', None)}:{vista_id}"
    memo = cache.get(chiave)
    if memo is None:
        vista = _vista(vista_id)
        if vista is None:
            return True
        try:
            # il queryset della classe: l'azienda della richiesta, senza le regole e i filtri (core.viste.registry)
            tutte = filtrate = type(vista).get_queryset(vista, request)
            for filtro in filtri:
                filtrate = filtro(vista, request, filtrate)
            memo = filtrate.count() != tutte.count()
        except Exception:
            log.exception("filtri dei moduli sulla vista %s: le previsioni salvate non si mostrano", vista_id)
            memo = True
        cache.set(chiave, memo, CACHE_SECONDI)
    return memo


def _visibile(pronta, request, spec):
    """L'utente può vedere la previsione, la cui app vale per l'azienda (lo controlla chi chiama, prima di costruire
    la specifica): Previsioni vale per l'azienda, ha il permesso e vede le viste da cui viene (un fatturato solo a chi
    vede le fatture)."""
    azienda, user = request.azienda, request.user
    if not (app_attiva("previsioni", azienda, user) and user.has_perm(pronta.permesso)):
        return False
    try:
        viste = [_vista(v) for v in viste_di(spec)]
    except ErroreInterrogazione:
        return False
    return all(v is not None and app_attiva(v.modulo, azienda, user) and v.has_view_permission(request) for v in viste)


def per_request(request):
    """Le previsioni pronte che l'utente della richiesta può vedere nell'azienda corrente, in ordine di registrazione:
    [{"chiave", "titolo", "app", "spec"}]."""
    azienda = getattr(request, "azienda", None)
    if azienda is None:
        return []
    elenco = []
    for pronta in _registro.values():
        if not app_attiva(pronta.app, azienda, request.user):
            continue                                  # spec e titolo possono dipendere dalle app dell'azienda
        spec = pronta.spec(azienda)
        if _visibile(pronta, request, spec):
            elenco.append({"chiave": pronta.chiave, "titolo": pronta.titolo_per(azienda), "app": pronta.app,
                           "spec": spec})
    return elenco


def dati_per(request, chiave):
    """La previsione pronta `chiave` per l'utente della richiesta: {"chiave", "titolo", "spec", "dati" (il risultato
    del motore, o None), "calcolata_il", "salvata", "errore"}. La salvata se l'utente vede tutte le viste di origine,
    altrimenti calcolata adesso con i suoi permessi (in cache per 10 minuti; un fallimento per un minuto). Gli errori
    arrivano come testo."""
    pronta, azienda = _registro[chiave], getattr(request, "azienda", None)
    esito = {"chiave": chiave, "titolo": "", "spec": None, "dati": None, "calcolata_il": None, "salvata": False,
             "errore": ""}
    if azienda is None or not app_attiva(pronta.app, azienda, request.user):
        return {**esito, "errore": NON_DISPONIBILE}
    spec = pronta.spec(azienda)
    esito.update(titolo=pronta.titolo_per(azienda), spec=spec)
    if not _visibile(pronta, request, spec):
        return {**esito, "errore": NON_DISPONIBILE}
    if not any(limitato(request, v, pronta.campi) for v in viste_di(spec)):
        riga = PrevisionePronta.objects.filter(azienda=azienda, chiave=chiave).first()
        if riga is None or riga.dati.get("spec") != spec:       # mai calcolata, o con un'altra specifica
            return {**esito, "salvata": True, "errore": NON_CALCOLATA}
        return {**esito, "salvata": True, "dati": riga.dati.get("risultato"), "calcolata_il": riga.calcolata_il,
                "errore": riga.dati.get("errore", "")}
    chiave_cache = f"previsioni:pronta:{request.user.pk}:{azienda.pk}:{chiave}"
    memo = cache.get(chiave_cache)
    if memo is None or memo["spec"] != spec:
        try:
            memo = {"spec": spec, "dati": calcola_pronta(pronta, spec, request), "calcolata_il": timezone.now()}
        except ErrorePrevisione as e:
            cache.set(chiave_cache, {"spec": spec, "errore": str(e)}, CACHE_ERRORE)
            return {**esito, "errore": str(e)}
        cache.set(chiave_cache, memo, CACHE_SECONDI)
    if "errore" in memo:
        return {**esito, "errore": memo["errore"]}
    return {**esito, "dati": memo["dati"], "calcolata_il": memo["calcolata_il"]}


# ---- Vendite (spec, «4 ter»): il fatturato se c'è Fatturazione, altrimenti l'ordinato ---------------------------

def _con_fatture(azienda):
    return app_attiva("fatturazione", azienda)


def _misura_vendite(azienda):
    return "fatturazione.fatturato" if _con_fatture(azienda) else "vendite.ordinato"


# i campi usati da fatturato (fatture: data, imponibile, stato, tipo, cliente) o ordinato (ordini: gli stessi, senza
# tipo) e dalle quantità per prodotto (righe vendute: ordine per la data, prodotto, quantità nell'unità del prodotto)
CAMPI_VENDITE = ("data", "imponibile", "stato", "tipo")
VISTA_PERMESSO = "previsioni.view_previsionepronta"
# le quantità per prodotto nell'unità del prodotto (quantita_base); le righe in un'unità che non si converte ce l'hanno
# vuota: si escludono e si contano (spec, «4 ter»)
PRODOTTI = {"vista": "vendite.righe_vendute", "data": "ordine__data", "misura": "sum:quantita_base",
            "filtri": {"quantita_base__isnull": False}, "raggruppa": "prodotto", "primi": 10, "per": "mese",
            "orizzonte": 3}


def _righe_senza_fattore(request):
    """{"esclusi_unita": quante righe vendute, tra quelle che l'utente vede, non hanno la quantità nell'unità del
    prodotto} (la pagina dice «N righe in un'altra unità senza fattore, escluse»)."""
    try:
        vista = interroga.vista_per_nome(PRODOTTI["vista"], request)
        r = interroga.aggrega(vista, request, misura="count", filtri={"quantita_base__isnull": True})
    except ErroreInterrogazione as e:
        raise ErrorePrevisione(str(e)) from e
    return {"esclusi_unita": r["totale"]}


registra("vendite.fatturato_mese",
         lambda azienda: "Fatturato previsto per mese" if _con_fatture(azienda) else "Ordinato previsto per mese",
         "vendite", VISTA_PERMESSO,
         lambda azienda: {"misura_aziendale": _misura_vendite(azienda), "per": "mese", "orizzonte": 3},
         CAMPI_VENDITE)
registra("vendite.prodotti", "Prodotti: quantità prevista, primi 10", "vendite", VISTA_PERMESSO,
         lambda azienda: {**PRODOTTI, "filtri": dict(PRODOTTI["filtri"])},
         ("ordine", "prodotto", "quantita_base"), aggiunte=_righe_senza_fattore)
registra("vendite.clienti", "Clienti: vendite previste, primi 10", "vendite", VISTA_PERMESSO,
         lambda azienda: {"misura_aziendale": _misura_vendite(azienda), "raggruppa": "cliente", "primi": 10,
                          "per": "mese", "orizzonte": 3},
         (*CAMPI_VENDITE, "cliente"))
