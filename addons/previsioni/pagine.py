"""La pagina «Previsioni» (una sezione per app), le card delle previsioni pronte, i widget della dashboard e la riga
di Vendite nella scheda prodotto.

Ogni previsione pronta si carica da sola con HTMX (`previsioni:pronta`): per chi non vede tutta la vista di origine
`dati_per` calcola al momento (fino a servizio.TIMEOUT_WEB per chiamata) e la pagina non deve aspettarla."""
from django.apps import apps
from django.urls import reverse
from django.utils.safestring import mark_safe

from core.viste import interroga
from core.viste.interroga import ErroreInterrogazione

from . import calcolo, esaurimenti, mie, motore, pronte, servizio
from .models import StatoCalcolo

PERMESSI_PAGINA = ("previsioni.view_previsionepronta", "previsioni.view_previsionearticolo")
PERMESSO_MAGAZZINO = "magazzino.view_movimento"     # quello delle Giacenze di Magazzino (anche «sotto scorta»)
PRIMI_ESAURIMENTI = 10
SENZA_SERVIZIO = "Il servizio di previsione non è configurato: si vedono le ultime previsioni salvate."


def puo_vedere_la_pagina(user):
    return any(user.has_perm(p) for p in PERMESSI_PAGINA)


def puo_aggiornare(request, cosa):
    """Il bottone «Aggiorna» (pagina e riquadro del prodotto) si mostra con il servizio acceso, il permesso di modifica
    e le previsioni calcolabili."""
    from .views import PERMESSI_AGGIORNA            # views importa questo modulo
    return (servizio.attivo(request.azienda, request.user) and request.user.has_perm(PERMESSI_AGGIORNA[cosa])
            and calcolo.eseguibile(cosa, request.azienda))


def _sezione_vendite(request):
    elenco = pronte.per_request(request)
    if not elenco:
        return None
    return {"pronte": [{"chiave": p["chiave"], "titolo": p["titolo"], "url": reverse("previsioni:pronta", args=[p["chiave"]])}
                       for p in elenco],
            "aggiorna": puo_aggiornare(request, StatoCalcolo.VENDITE),
            "avviso": esaurimenti.avviso(request.azienda, StatoCalcolo.VENDITE)}


def _riga_esaurimento(r):
    return {"prodotto": r.prodotto, "magazzino": r.magazzino or "Tutti i magazzini", "riordino": r.riordino,
            "esaurimento": r.esaurimento, "fascia": esaurimenti.fascia(r) if r.esaurimento else "",
            "stato": r.get_stato_display(), "affidabilita": str(r.affidabilita.get("livello", "")).capitalize() or "—",
            "motivo": (r.affidabilita.get("motivi") or [""])[0]}


def magazzino_visibile(request):
    """Spec: chi non ha Magazzino non vede le previsioni del magazzino, anche con il modulo. Magazzino acceso per
    l'azienda della richiesta e il permesso di leggerne le giacenze (il permesso delle previsioni lo guarda la vista)."""
    user = request.user
    return pronte.app_attiva("magazzino", getattr(request, "azienda", None), user) and user.has_perm(PERMESSO_MAGAZZINO)


def vista_esaurimenti(request):
    """La vista «Articoli in esaurimento» per chi guarda, o None se non la vede (Previsioni per l'azienda, permesso
    delle previsioni, Magazzino: ArticoliInEsaurimentoView.has_view_permission). Le previsioni del magazzino si leggono
    sempre dal suo `get_queryset`: azienda, regole di riga del ruolo e filtri dei moduli, come la lista."""
    if getattr(request, "azienda", None) is None or not pronte.app_attiva("previsioni", request.azienda, request.user):
        return None
    try:
        return interroga.vista_per_nome("previsioni.esaurimenti", request)
    except ErroreInterrogazione:
        return None


def _sezione_magazzino(request):
    azienda = request.azienda
    vista = vista_esaurimenti(request)
    if vista is None:
        return None
    righe = list(vista.get_queryset(request)[:PRIMI_ESAURIMENTI])
    return {"righe": [_riga_esaurimento(r) for r in righe], "modello": righe[0].modello if righe else "",
            "calcolata_il": max((r.calcolata_il for r in righe), default=None),
            "aggiorna": puo_aggiornare(request, StatoCalcolo.MAGAZZINO),
            "avviso": esaurimenti.avviso(azienda, StatoCalcolo.MAGAZZINO)}


def _nuova_previsione(request):
    """«Nuova previsione» (costruttore di Analisi) solo con Analisi attiva per l'azienda e il permesso di creare grafici."""
    if not (apps.is_installed("grafici") and pronte.app_attiva("grafici", request.azienda, request.user)
            and request.user.has_perm("grafici.add_grafico")):
        return ""
    return f'{reverse("grafici:costruttore")}?tipo=previsione'


def contesto_pagina(request):
    vendite, magazzino = _sezione_vendite(request), _sezione_magazzino(request)
    return {"vendite": vendite, "magazzino": magazzino, "vuota": vendite is None and magazzino is None,
            "mie": mie.sezione(request),
            "senza_servizio": not servizio.attivo(request.azienda, request.user), "messaggio_senza_servizio": SENZA_SERVIZIO,
            "nuova_previsione_url": _nuova_previsione(request)}


# ---------- una previsione pronta ----------

def _riga_serie(f):
    return {"periodo": f[0], "basso": f[1], "mediana": f[2], "alto": f[3]}


def contesto_pronta(request, chiave):
    """Il contesto della card di una previsione pronta (`_pronta.html`). KeyError se la chiave non esiste."""
    esito = pronte.dati_per(request, chiave)
    dati = esito["dati"]
    c = {"titolo": esito["titolo"], "errore": esito["errore"], "dati": dati, "attribuzione": bool(dati)}
    if not dati:
        return c
    c.update(modello=dati.get("modello", ""), calcolata_il=esito["calcolata_il"], calcolata_ora=not esito["salvata"],
             esclusi_unita=dati.get("esclusi_unita", 0), esclusi=dati.get("esclusi", 0))
    if "gruppi" in dati:
        c["tabella"] = motore.come_tabella(dati)
    else:
        c.update(svg=mark_safe(motore.svg_previsione(dati, esito["titolo"])),
                 periodi=[_riga_serie(f) for f in dati.get("futuro", [])], totale=dati.get("totale"),
                 affidabilita=dati.get("affidabilita", {}),
                 motivo=(dati.get("affidabilita", {}).get("motivi") or [""])[0])
    return c


# ---------- Vendite nella scheda prodotto ----------

def vendite_prodotto(request, pk):
    """La riga «Vendite previste nei prossimi N mesi» del prodotto `pk`: il totale del suo gruppo in `vendite.prodotti`,
    o None se il gruppo non c'è («non tra i 10 più venduti»). Il contesto è vuoto se la previsione non è disponibile."""
    esito = pronte.dati_per(request, "vendite.prodotti")
    dati = esito["dati"]
    if not dati:
        return {"errore": esito["errore"]}
    gruppo = next((g for g in dati.get("gruppi", []) if str(g["chiave"]) == str(pk)), None)
    c = {"mesi": len(dati.get("periodi", [])) or 3, "modello": dati.get("modello", ""), "gruppo": gruppo,
         "calcolata_il": esito["calcolata_il"], "calcolata_ora": not esito["salvata"]}
    if gruppo:
        c.update(totale=gruppo["totale"], affidabilita=gruppo["affidabilita"],
                 motivo=(gruppo["affidabilita"].get("motivi") or [""])[0])
    return c


def vendite_prodotti_visibili(request):
    return any(p["chiave"] == "vendite.prodotti" for p in pronte.per_request(request))


# ---------- i widget della dashboard ----------

def widget(request):
    """Le previsioni pronte come widget per la libreria della dashboard: la card si carica con HTMX quando il widget
    è in vista (forma di `hooks.widget_dashboard`)."""
    return [{"id": f"previsioni:{p['chiave']}", "tipo": "previsione", "titolo": p["titolo"], "app": "Previsioni",
             "su_richiesta": True, "larghezza": 2, "template": "previsioni/_widget.html",
             "carica": lambda p=p: {"url": reverse("previsioni:pronta", args=[p["chiave"]])}}
            for p in pronte.per_request(request)]
