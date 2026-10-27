"""Registro delle ModelView: per modulo (namespace URL) e per modello."""
import importlib
import importlib.util

_viste: dict[str, list] = {}
_per_modello: dict = {}


def register(cls):
    modulo = cls.__module__.split(".")[0]
    vista = cls(modulo)
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
