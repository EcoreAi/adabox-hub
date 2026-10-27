"""Punti di aggancio tra moduli: sezioni aggiunte al dettaglio di un modello altrui."""
from collections import defaultdict

_sezioni = defaultdict(list)   # "app.model" -> [dict(template, order, permission)]


def _chiave(model):
    return model.lower() if isinstance(model, str) else model._meta.label_lower


def sezione_dettaglio(model, template, order=100, permission=None):
    """Da chiamare nel ready() dell'app: il dettaglio di `model` ("app.Model" o classe) includerà
    `template` con `obj` nel contesto, nell'ordine di `order`, solo per chi ha `permission`."""
    _sezioni[_chiave(model)].append({"template": template, "order": order, "permission": permission})


def sezioni_per(model, request):
    user = request.user
    visibili = [s for s in _sezioni.get(_chiave(model), [])
                if s["permission"] is None or user.is_superuser or user.has_perm(s["permission"])]
    return sorted(visibili, key=lambda s: s["order"])


def svuota():
    """Solo per i test."""
    _sezioni.clear()
