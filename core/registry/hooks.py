"""Punti di aggancio tra moduli: sezioni aggiunte al dettaglio di un modello altrui, voci della testata, sezioni in
testa alla dashboard, voci nella pagina «In tasca» e azioni che un modulo aggiunge a un punto preciso di un template
altrui."""
from collections import defaultdict

_sezioni = defaultdict(list)   # "app.model" -> [dict(template, order, permission)]
_testata = []                  # [dict(template, order, permission)] voci della barra in alto
_dashboard = []                # [dict(template, order, permission)] sezioni in testa alla dashboard
_azioni = defaultdict(list)    # "chiave" -> [dict(template, order, permission)] azioni in un punto di un template
_widget = []                   # [dict(funzione, modulo, permission)] altri widget per la libreria della dashboard
_portale = []                  # prefissi degli indirizzi che i clienti del portale possono aprire
_pagine_app = []               # pagine che un modulo aggiunge dentro le altre app (es. «Aree di lavoro» dell'assistente)
_parti_dashboard = set()       # app le cui pagine sono schede della dashboard (es. Analisi)
_fonti_ricerca = []            # [dict(funzione, modulo, permission)] altre cose da trovare con «Cerca ovunque»
_tasca = []                    # [dict(etichetta, url_name, icona, permission, ...)] voci dei moduli nella pagina «In tasca»


def _chiave(model):
    return model.lower() if isinstance(model, str) else model._meta.label_lower


def sezione_dettaglio(model, template, order=100, permission=None):
    """Da chiamare nel ready() dell'app: il dettaglio di `model` ("app.Model", classe o "*" per tutti) includerà
    `template` con `obj` nel contesto, nell'ordine di `order`, solo per chi ha `permission`."""
    _sezioni[_chiave(model)].append({"template": template, "order": order, "permission": permission})


def sezioni_per(model, request):
    user = request.user
    visibili = [s for s in _sezioni.get(_chiave(model), []) + _sezioni.get("*", [])
                if s["permission"] is None or user.is_superuser or user.has_perm(s["permission"])]
    return sorted(visibili, key=lambda s: s["order"])


def voce_testata(template, order=100, permission=None):
    """Da chiamare nel ready() dell'app: `template` è incluso nella barra in alto, prima del profilo
    (es. l'icona dei messaggi con il contatore), solo per chi ha `permission`."""
    voce = {"template": template, "order": order, "permission": permission}
    if voce not in _testata:
        _testata.append(voce)


def voci_testata(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return []
    from .modules import disattivati
    spenti = disattivati()                         # i template delle app seguono «<modulo>/...»
    visibili = [v for v in _testata if (v["permission"] is None or user.is_superuser or user.has_perm(v["permission"]))
                and v["template"].split("/", 1)[0] not in spenti]
    return sorted(visibili, key=lambda v: v["order"])


def _visibili(voci, request):
    """Le voci permesse all'utente, senza quelle dei moduli spenti (i template delle app seguono «<modulo>/...»)."""
    user = getattr(request, "user", None)
    from .modules import disattivati
    if user is None or not user.is_authenticated:          # chi non è entrato vede solo le voci pubbliche
        spenti = disattivati()
        return sorted([v for v in voci if v.get("pubblica") and v["permission"] is None
                       and v["template"].split("/", 1)[0] not in spenti], key=lambda v: v["order"])
    spenti = disattivati()
    return sorted([v for v in voci if (v["permission"] is None or user.is_superuser or user.has_perm(v["permission"]))
                   and v["template"].split("/", 1)[0] not in spenti], key=lambda v: v["order"])


def voce_tasca(etichetta, url_name, icona="zap", permission=None, sotto="", conta=None, order=100, scorciatoia=False, modulo=None):
    """Da chiamare nel ready() dell'app: una voce nella pagina «In tasca» (quella del telefono), per esempio
    «Scansiona documento» a un tocco dall'avvio. La vede chi ha `permission`, se l'app è accesa, è attiva per l'azienda
    corrente ed è tra quelle dei suoi dipartimenti.

    - `url_name`: il nome URL della pagina; l'app è la sua prima parte («iem:scansiona» → iem), o `modulo`;
    - `icona`: il nome di un'icona del tema (#icon-<nome>); `sotto`: la riga piccola sotto l'etichetta;
    - `conta`: una funzione che riceve la richiesta e dà il numero da mostrare nel bollino (None o 0 = niente);
    - `scorciatoia`: la voce va anche tra le scorciatoie dell'icona dell'app installata (poche: il telefono ne mostra
      tre o quattro). Si apre da `/tasca/?apri=<url_name>`, che controlla gli stessi permessi."""
    voce = {"etichetta": etichetta, "url_name": url_name, "icona": icona, "permission": permission, "sotto": sotto, "conta": conta,
            "order": order, "scorciatoia": scorciatoia, "modulo": modulo or url_name.split(":", 1)[0]}
    if not any(v["url_name"] == url_name for v in _tasca):
        _tasca.append(voce)


def voci_tasca(request):
    """Le voci dei moduli per «In tasca» che questa persona può usare, già risolte: [{etichetta, url, url_name, icona,
    sotto, conta}]."""
    from django.urls import NoReverseMatch, reverse

    from core import dipartimenti

    from .modules import disattivati, per_azienda
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return []
    spenti, azienda, voci = disattivati(), getattr(request, "azienda", None), []
    for v in sorted(_tasca, key=lambda v: v["order"]):
        if v["modulo"] in spenti or not per_azienda(v["modulo"], azienda, user):
            continue
        if not user.is_superuser and not dipartimenti.ammessa(user, v["modulo"]):
            continue
        if v["permission"] and not user.has_perm(v["permission"]):
            continue
        try:
            url = reverse(v["url_name"])
        except NoReverseMatch:
            continue
        conta = None
        if v["conta"] is not None:
            try:
                conta = v["conta"](request) or None
            except Exception:                              # noqa: BLE001 - il bollino non deve far cadere la pagina
                conta = None
        voci.append({"etichetta": v["etichetta"], "url": url, "url_name": v["url_name"], "icona": v["icona"], "sotto": v["sotto"],
                     "conta": conta})
    return voci


def scorciatoie_tasca():
    """Per il manifest dell'app installata (uguale per tutti: non c'è una persona): le voci che lo hanno chiesto, dei
    moduli accesi. Chi le tocca passa da /tasca/?apri=, che controlla permessi, azienda e dipartimenti."""
    from .modules import disattivati
    spenti = disattivati()
    return [{"name": v["etichetta"], "url": f"/tasca/?apri={v['url_name']}"} for v in sorted(_tasca, key=lambda v: v["order"])
            if v["scorciatoia"] and v["modulo"] not in spenti]


def sezione_dashboard(template, order=100, permission=None):
    """Da chiamare nel ready() dell'app: `template` è incluso in testa alla dashboard, sotto il titolo (es. le schede
    delle pagine di Analisi), solo per chi ha `permission`."""
    voce = {"template": template, "order": order, "permission": permission}
    if voce not in _dashboard:
        _dashboard.append(voce)


def sezioni_dashboard(request):
    return _visibili(_dashboard, request)


def parte_della_dashboard(app):
    """Da chiamare nel ready() dell'app: le sue pagine sono schede della dashboard. Non ha una voce sua nella barra in alto,
    e nelle sue pagine l'header resta quello della Dashboard (voce evidenziata, niente sottomenu dell'app)."""
    _parti_dashboard.add(app)


def parti_dashboard():
    return frozenset(_parti_dashboard)


def widget_dashboard(funzione, modulo, permission=None):
    """Da chiamare nel ready() dell'app: `funzione` (percorso puntato, riceve la richiesta) dà altri widget da mettere
    in dashboard: [{id, tipo, titolo, app, su_richiesta, template, carica}]. `carica()` dà il widget completo quando serve."""
    voce = {"funzione": funzione, "modulo": modulo, "permission": permission}
    if voce not in _widget:
        _widget.append(voce)


def widget_extra(request):
    from .modules import disattivati
    user = request.user
    spenti = disattivati()
    return [v["funzione"] for v in _widget if v["modulo"] not in spenti and (v["permission"] is None or user.is_superuser or user.has_perm(v["permission"]))]


def fonte_ricerca(funzione, modulo, permission=None):
    """Da chiamare nel ready() dell'app: `funzione` (percorso puntato, riceve la richiesta) dà altre cose che «Cerca
    ovunque» trova per titolo, con la visibilità di chi cerca: {"gruppo": "Grafici e pagine di Analisi", "grafici": True,
    "voci": [{"titolo", "url", "sotto"}]}. `grafici`: se nessuna voce corrisponde, la ricerca propone di chiedere ad Ada."""
    voce = {"funzione": funzione, "modulo": modulo, "permission": permission}
    if voce not in _fonti_ricerca:
        _fonti_ricerca.append(voce)


def fonti_ricerca(request):
    from .modules import disattivati
    user = request.user
    spenti = disattivati()
    return [v["funzione"] for v in _fonti_ricerca if v["modulo"] not in spenti
            and (v["permission"] is None or user.is_superuser or user.has_perm(v["permission"]))]


def azione(chiave, template, order=100, permission=None, pubblica=False):
    """Da chiamare nel ready() dell'app: dove un template altrui scrive {% agganci "chiave" %} compare `template`,
    con il contesto di quel punto (es. «Salva in Analisi» sotto un grafico dell'assistente: chiave «ai.artifact»).
    `pubblica`: compare anche a chi non ha fatto l'accesso (es. i bottoni nella pagina di login)."""
    voce = {"template": template, "order": order, "permission": permission}
    if pubblica:
        voce["pubblica"] = True
    if voce not in _azioni[chiave]:
        _azioni[chiave].append(voce)


def azioni_per(chiave, request):
    return _visibili(_azioni.get(chiave, []), request)


def svuota():
    """Solo per i test."""
    _sezioni.clear()
    _testata.clear()
    _dashboard.clear()
    _azioni.clear()
    _widget.clear()
    _fonti_ricerca.clear()


def percorso_portale(prefisso):
    """Da chiamare nel ready() dell'app: gli utenti esterni (clienti del portale) possono aprire gli indirizzi che
    iniziano con `prefisso`, es. "/fatturazione/portale/". Il resto dell'applicazione resta chiuso per loro."""
    if prefisso not in _portale:
        _portale.append(prefisso)


def percorsi_portale():
    """I prefissi del portale dei moduli accesi (i loro indirizzi iniziano con «/<modulo>/»)."""
    from .modules import disattivati
    spenti = disattivati()
    return tuple(p for p in _portale if p.strip("/").split("/", 1)[0] not in spenti)


def pagina_app(percorso, vista, nome, etichetta, mostra=None, escluse=()):
    """Da chiamare nel ready() dell'app: la pagina `vista` si monta dentro ogni app applicazione, al suo indirizzo
    «/<app>/<percorso>» e nel suo namespace (quindi con il menu di quell'app), e compare nel menu dell'app quando
    `mostra(request, slug)` è vero. La vista riceve l'app da request.resolver_match.namespace."""
    voce = {"percorso": percorso, "vista": vista, "nome": nome, "etichetta": etichetta, "mostra": mostra, "escluse": set(escluse)}
    if not any(v["nome"] == nome for v in _pagine_app):
        _pagine_app.append(voce)


def pagine_app():
    return list(_pagine_app)
