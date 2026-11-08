"""Regole di accesso per ruolo dichiarate dall'interfaccia (PLT-03):
- PermessoCampo: un campo nascosto o in sola lettura in form, dettaglio, lista, export, API e per l'assistente;
- RegolaRiga: quali record si vedono, come filtro sul queryset della vista (quindi ovunque passi da get_queryset).
Il superuser e chi non ha un ruolo non hanno limiti in più. Le regole si leggono una volta per richiesta."""
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db.models import Q


def _utente(request):
    return getattr(request, "user", None)


def ruolo_di(request):
    """Il ruolo dell'utente della richiesta, o None (superuser, anonimo, senza ruolo)."""
    utente = _utente(request)
    if utente is None or not getattr(utente, "is_authenticated", False) or getattr(utente, "is_superuser", False):
        return None
    memo = getattr(request, "_ruolo_regole", "x") if not isinstance(request, dict) else "x"
    if memo != "x":
        return memo
    from core.models import Ruolo
    ruolo = Ruolo.objects.filter(profili__utente=utente).values_list("pk", flat=True).first()
    try:
        request._ruolo_regole = ruolo
    except AttributeError:
        pass
    return ruolo


def _chiave(vista):
    return f"{vista.modulo}.{vista.slug}"


def _permessi(vista, request):
    ruolo = ruolo_di(request)
    if ruolo is None:
        return {}
    memo = getattr(request, "_permessi_campi", None)
    if memo is None:
        memo = {}
        try:
            request._permessi_campi = memo
        except AttributeError:
            pass
    chiave = _chiave(vista)
    if chiave not in memo:
        from core.models import PermessoCampo
        memo[chiave] = dict(PermessoCampo.objects.filter(vista=chiave, ruolo_id=ruolo).values_list("campo", "livello"))
    return memo[chiave]


def nascosti(vista, request):
    from core.models import PermessoCampo
    return {c for c, livello in _permessi(vista, request).items() if livello == PermessoCampo.NASCOSTO}


def bloccati(vista, request):
    from core.models import PermessoCampo
    return {c for c, livello in _permessi(vista, request).items() if livello == PermessoCampo.SOLA_LETTURA}


def _condizione(regola, request):
    campo, op, valore = regola.campo, regola.operatore, regola.valore.strip()
    if op == "utente":
        return Q(**{campo: _utente(request)})
    if op == "uguale":
        return Q(**{campo: valore})
    if op == "diverso":
        return ~Q(**{campo: valore})
    if op == "in":
        return Q(**{f"{campo}__in": [v.strip() for v in valore.split(",") if v.strip()]})
    if op == "vuoto":
        return Q(**{f"{campo}__isnull": True}) | Q(**{campo: ""}) if _testuale(regola) else Q(**{f"{campo}__isnull": True})
    if op == "pieno":
        return ~(Q(**{f"{campo}__isnull": True}) | Q(**{campo: ""})) if _testuale(regola) else Q(**{f"{campo}__isnull": False})
    if op == "contiene":
        return Q(**{f"{campo}__icontains": valore})
    if op == "min":
        return Q(**{f"{campo}__gte": valore})
    if op == "max":
        return Q(**{f"{campo}__lte": valore})
    return Q()


def _testuale(regola):
    return getattr(regola, "_testuale", False)


def applica_righe(vista, request, qs):
    """Il queryset con le regole sulle righe del ruolo; una regola rotta (campo sparito) nasconde tutto, mai di più."""
    ruolo = ruolo_di(request)
    if ruolo is None:
        return qs
    from core.models import RegolaRiga
    regole = list(RegolaRiga.objects.filter(vista=_chiave(vista), ruolo_id=ruolo, attiva=True))
    for r in regole:
        try:
            f = campo_del_percorso(vista.model, r.campo)
            r._testuale = f is not None and f.get_internal_type() in ("CharField", "TextField", "EmailField")
            qs = qs.filter(_condizione(r, request))
        except (FieldDoesNotExist, ValueError, ValidationError, TypeError):
            return qs.none()
    return qs


def campo_del_percorso(modello, percorso):
    """Il campo finale di «a__b__c» (FieldDoesNotExist se non esiste)."""
    f = None
    for parte in percorso.split("__"):
        f = modello._meta.get_field(parte)
        modello = f.related_model if f.is_relation else modello
    return f


def adatta_form(form_class, vista, request):
    """La classe del form senza i campi nascosti e con quelli in sola lettura disabilitati (Django tiene il valore
    salvato, qualunque cosa arrivi dal browser)."""
    via, fermi = nascosti(vista, request), bloccati(vista, request)
    if not via and not fermi:
        return form_class

    class Form(form_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for nome in via:
                self.fields.pop(nome, None)
            for nome in fermi:
                if nome in self.fields:
                    self.fields[nome].disabled = True
                    self.fields[nome].help_text = (self.fields[nome].help_text + " · " if self.fields[nome].help_text else "") + "in sola lettura per il tuo ruolo"
    Form.__name__ = form_class.__name__
    return Form
