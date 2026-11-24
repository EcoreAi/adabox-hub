"""La ricerca in tutte le app: i campi di ricerca di ogni vista che l'utente può vedere, con i suoi permessi e la sua
azienda. Una query per vista: per questo si cerca all'invio, con un tetto di tempo, e pochi risultati per vista."""
import logging
import re
import time
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import NoReverseMatch

from .viste import filtri
from .viste.interroga import viste_accessibili

log = logging.getLogger("core.cerca")
PER_VISTA = 5
TEMPO_MASSIMO = 3.0
LUNGHEZZA_MINIMA = 2


def cerca(request, testo):
    """([{"vista", "app", "totale", "url", "voci": [{"titolo", "url"}]}], completa)."""
    gruppi, inizio = [], time.monotonic()
    for vista in viste_accessibili(request):
        if not vista.search_fields:
            continue
        if time.monotonic() - inizio > TEMPO_MASSIMO:
            return gruppi, False
        qs = filtri.applica(vista, request, vista.get_queryset(request), parametri={"q": testo})
        voci = list(qs[:PER_VISTA + 1])
        if not voci:
            continue
        try:
            righe = [{"titolo": str(o), "url": vista.url("dettaglio", pk=o.pk)} for o in voci[:PER_VISTA]]
            url = f"{vista.url('lista')}?q="
        except NoReverseMatch:
            continue
        gruppi.append({"vista": str(vista.verbose_name_plural).capitalize(), "app": vista.modulo, "url": url, "voci": righe, "altri": len(voci) > PER_VISTA})
    return gruppi, True


# ---------- scorciatoie: grafici, pagine e voci di menu per parole ----------

# parole che non dicono che cosa si cerca («grafico delle vendite di quest'anno» → vendite)
VUOTE = {"il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "del", "dello", "della", "dei", "degli", "delle",
         "a", "al", "allo", "alla", "ai", "agli", "alle", "da", "dal", "dalla", "in", "nel", "nella", "con", "su", "per",
         "e", "o", "che", "mi", "dove", "trovo", "voglio", "vorrei", "vedere", "mostra", "mostrami", "cerca", "trova"}
# parole generiche: in una frase non dicono che cosa si cerca («grafico delle vendite» → vendite), da sole sì: chi cerca
# «Grafici» o «Statistiche» vuole quelle pagine (prima non trovava nulla)
GENERICHE = {"grafico", "grafici", "pagina", "pagine", "report", "statistica", "statistiche", "andamento"}
# parole di tempo: aiutano a ordinare ma non sono obbligatorie (il titolo raramente le contiene)
TEMPO = {"quest", "questo", "questa", "anno", "mese", "mesi", "settimana", "oggi", "ieri", "scorso", "scorsa",
         "ultimo", "ultimi", "trimestre", "mensile", "mensili", "annuale"}
PAROLA = re.compile(r"[a-zà-ù0-9]+")
MAX_SCORCIATOIE = 8


def parole(testo):
    """(parole che il titolo deve contenere, parole di tempo facoltative). Le parole generiche contano solo se non ce
    n'è nessun'altra."""
    tutte = [p for p in PAROLA.findall((testo or "").lower()) if p not in VUOTE]
    richieste = [p for p in tutte if p not in TEMPO and p not in GENERICHE]
    return richieste or [p for p in tutte if p in GENERICHE], [p for p in tutte if p in TEMPO]


def _radice(p):
    return p[:max(4, len(p) - 2)] if len(p) > 4 else p          # «vendite», «vendita» → «vend»; «scadenz…» → «scaden»


def _sinonimi():
    """{radice: radici equivalenti} dalle misure aziendali: «vendite» vale «fatturato», «ricavi»…"""
    from . import misure
    gruppi = {}
    for m in misure.tutte():
        parole_misura = {_radice(p) for frase in (m.etichetta, *m.sinonimi) for p in PAROLA.findall(frase.lower())
                         if p not in VUOTE and len(p) > 2}
        for r in parole_misura:
            gruppi.setdefault(r, set()).update(parole_misura)
    return gruppi


def punteggio(titolo, richieste, facoltative=(), sinonimi=None):
    """0 se manca una parola richiesta (o un suo sinonimo); altrimenti più alto per le corrispondenze esatte."""
    if not richieste:
        return 0
    sinonimi = _sinonimi() if sinonimi is None else sinonimi
    nel_titolo = PAROLA.findall((titolo or "").lower())
    radici = {_radice(p) for p in nel_titolo}
    punti = 0
    for p in richieste:
        if any(t.startswith(p) for t in nel_titolo):
            punti += 3
        elif _radice(p) in radici:
            punti += 2
        elif sinonimi.get(_radice(p), set()) & radici:
            punti += 1
        else:
            return 0
    return punti + sum(1 for p in facoltative if any(t.startswith(p) for t in nel_titolo))


# Le pagine del kernel che non sono voci di menu di un'app: (titolo, nome URL, parole con cui le si cerca, permesso).
# Le pagine dei moduli arrivano dalle loro fonti di ricerca (hooks.fonte_ricerca), con le stesse "parole".
PAGINE_KERNEL = (
    ("Dashboard", "core:dashboard", "home cruscotto indicatori kpi", None),
    ("In tasca", "core:tasca", "telefono cellulare smartphone", None),
    ("Profilo", "core:profilo", "account dati personali", None),
    ("Cambia password", "password_change", "password sicurezza accesso", None),
    ("Le mie app nel menu", "core:le_mie_app", "barra menu ordine app", None),
    ("Applicazioni", "core:applicazioni", "app moduli catalogo installa attiva acquista", "core.view_modulo"),
    ("Ordine nel menu", "core:impostazioni_barra", "barra menu app ordine", "core.change_parametro"),
    ("Impostazioni", "core:impostazioni", "configurazione parametri opzioni", "core.change_parametro"),
    ("Utenti e ruoli", "core:utenti", "persone permessi accessi account", "auth.change_user"),
    ("Chi può fare cosa", "core:matrice", "permessi ruoli matrice", "auth.change_user"),
)


def _pagine(request):
    from django.urls import NoReverseMatch, reverse
    voci = []
    for titolo, nome, parole_chiave, permesso in PAGINE_KERNEL:
        if permesso and not request.user.has_perm(permesso):
            continue
        try:
            voci.append({"titolo": titolo, "url": reverse(nome), "sotto": "Pagina", "parole": parole_chiave})
        except NoReverseMatch:
            continue
    return {"gruppo": "Pagine", "voci": voci}


def _menu(request):
    from .registry import modules
    voci = [{"titolo": f"{a['label']} › {v['label']}", "url": v["url"], "sotto": "Voce di menu"}
            for a in modules.app_visibili(request.user) for v in a["menu"]]
    return {"gruppo": "Menu", "voci": voci}


def scorciatoie(request, testo):
    """([{"gruppo", "voci": [{"titolo", "url", "sotto"}]}], nessun grafico trovato tra le fonti di grafici). Una voce si
    trova per il titolo e per le sue "parole" (le pagine: «Statistiche» anche con «dashboard»); un indirizzo compare una
    volta sola, nel primo gruppo che lo trova."""
    from .lavori import risolvi
    from .registry import hooks
    richieste, facoltative = parole(testo)
    if not richieste:
        return [], False
    sinonimi = _sinonimi()
    fonti = [_pagine(request)]
    for funzione in hooks.fonti_ricerca(request):
        try:
            fonti.append(risolvi(funzione)(request))
        except Exception:                                # una fonte rotta non spegne la ricerca
            log.exception("fonte di ricerca %s", funzione)
    fonti.append(_menu(request))
    gruppi, grafici_cercati, grafici_trovati, visti = [], False, False, set()
    for f in fonti:
        trovate = sorted(((punteggio(f"{v['titolo']} {v.get('parole', '')}", richieste, facoltative, sinonimi), v)
                          for v in f["voci"] if v["url"] not in visti), key=lambda x: -x[0])
        voci = [{k: x for k, x in v.items() if k != "parole"} for punti, v in trovate if punti][:MAX_SCORCIATOIE]
        visti.update(v["url"] for v in voci)
        grafici_cercati = grafici_cercati or f.get("grafici", False)
        grafici_trovati = grafici_trovati or (f.get("grafici", False) and bool(voci))
        if voci:
            gruppi.append({"gruppo": f["gruppo"], "voci": voci})
    # «Chiedi ad Ada di disegnarlo» solo se si cercava qualcosa da disegnare, non solo «grafici» o «statistiche»
    specifiche = any(p not in GENERICHE for p in richieste)
    return gruppi, grafici_cercati and not grafici_trovati and specifiche


def link_ada(request, testo):
    """L'indirizzo della chat con la domanda già scritta, se l'assistente c'è e l'utente lo può usare."""
    from django.urls import NoReverseMatch, reverse
    if not request.user.has_perm("ai.view_conversazione"):
        return ""
    try:
        return f"{reverse('ai:chat')}?{urlencode({'chiedi': testo})}"
    except NoReverseMatch:
        return ""


@login_required
def pagina(request):
    testo = request.GET.get("q", "").strip()[:100]
    abbastanza = len(testo) >= LUNGHEZZA_MINIMA
    gruppi, completa = (cerca(request, testo) if abbastanza else ([], True))
    scorciatoie_trovate, nessun_grafico = scorciatoie(request, testo) if abbastanza else ([], False)
    return render(request, "core/cerca.html", {
        "q": testo, "gruppi": gruppi, "completa": completa, "troppo_corta": 0 < len(testo) < LUNGHEZZA_MINIMA,
        "scorciatoie": scorciatoie_trovate, "ada": link_ada(request, testo) if nessun_grafico else ""})
