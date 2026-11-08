"""Registro delle ModelView: per modulo (namespace URL) e per modello."""
import importlib
import importlib.util

_viste: dict[str, list] = {}
_per_modello: dict = {}


def _con_regole(vista):
    """Le regole di accesso per ruolo (core.regole) valgono per ogni vista, anche quelle che ridefiniscono
    get_queryset e get_form_class: si avvolgono i metodi dell'istanza, una volta sola."""
    from core import regole
    classe = type(vista)                      # i metodi della classe legati a questa istanza (anche a una sua copia)
    queryset, form = classe.get_queryset.__get__(vista), classe.get_form_class.__get__(vista)

    def get_queryset(request):
        return regole.applica_righe(vista, request, queryset(request))

    def get_form_class(request=None):
        classe = form(request)
        return regole.adatta_form(classe, vista, request) if request is not None else classe
    vista.get_queryset, vista.get_form_class = get_queryset, get_form_class


def register(cls):
    modulo = cls.__module__.split(".")[0]
    vista = cls(modulo)
    _con_regole(vista)
    _viste.setdefault(modulo, []).append(vista)
    _per_modello[vista.model] = vista
    return cls


def viste_di(modulo):
    return list(_viste.get(modulo, []))


def per_modello(model):
    return _per_modello.get(model)


def urlpatterns(modulo):
    return [p for v in viste_di(modulo) for p in v.get_urls()]


def autodiscover(moduli):
    """Importa <slug>.views dei moduli dati (come admin.autodiscover): è lì che @register viene eseguito."""
    for slug in moduli:
        if importlib.util.find_spec(f"{slug}.views"):
            importlib.import_module(f"{slug}.views")


def svuota():
    """Solo per i test."""
    _viste.clear()
    _per_modello.clear()
