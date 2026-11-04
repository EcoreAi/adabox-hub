"""Punti di aggancio tra moduli: sezioni aggiunte al dettaglio di un modello altrui, voci della testata, sezioni in
testa alla dashboard e azioni che un modulo aggiunge a un punto preciso di un template altrui."""
from collections import defaultdict

_sezioni = defaultdict(list)   # "app.model" -> [dict(template, order, permission)]
_testata = []                  # [dict(template, order, permission)] voci della barra in alto
_dashboard = []                # [dict(template, order, permission)] sezioni in testa alla dashboard
_azioni = defaultdict(list)    # "chiave" -> [dict(template, order, permission)] azioni in un punto di un template


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
    if user is None or not user.is_authenticated:
        return []
    from .modules import disattivati
    spenti = disattivati()
    return sorted([v for v in voci if (v["permission"] is None or user.is_superuser or user.has_perm(v["permission"]))
                   and v["template"].split("/", 1)[0] not in spenti], key=lambda v: v["order"])


def sezione_dashboard(template, order=100, permission=None):
    """Da chiamare nel ready() dell'app: `template` è incluso in testa alla dashboard, sotto il titolo (es. le schede
    delle pagine di Analisi), solo per chi ha `permission`."""
    voce = {"template": template, "order": order, "permission": permission}
    if voce not in _dashboard:
        _dashboard.append(voce)


def sezioni_dashboard(request):
    return _visibili(_dashboard, request)


def azione(chiave, template, order=100, permission=None):
    """Da chiamare nel ready() dell'app: dove un template altrui scrive {% agganci "chiave" %} compare `template`,
    con il contesto di quel punto (es. «Salva in Analisi» sotto un grafico dell'assistente: chiave «ai.artifact»)."""
    voce = {"template": template, "order": order, "permission": permission}
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
