"""Template del tema: un modulo attivo porta i suoi template (es. `zenpark.tema`, cartella addons/zenpark/tema/templates)
e per le aziende con quel tema vengono prima di tutti gli altri. È TEMA_APP, ma per tema invece che per istanza.

Il loader è il primo della lista (config/settings.py) e legge il tema della richiesta in corso: il middleware la mette in
una ContextVar, e il tema si calcola solo quando serve un template (theme.context_processors.tema_della_richiesta).
Fuori da una richiesta (worker, email) nessun template del tema: tutto come prima."""
import contextvars
import functools
import importlib.util
import re
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.template import Origin, TemplateDoesNotExist
from django.template.loaders.base import Loader as LoaderBase
from django.utils._os import safe_join

PACCHETTO_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
_corrente = contextvars.ContextVar("tema_template", default=None)      # una richiesta, o il nome di un pacchetto


@functools.lru_cache(maxsize=64)
def _cartella(pacchetto, attivi):
    if not PACCHETTO_RE.match(pacchetto or "") or pacchetto.split(".")[0] not in attivi:
        return None
    try:
        spec = importlib.util.find_spec(pacchetto)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    cartella = Path(list(spec.submodule_search_locations)[0]) / "templates"
    return cartella if cartella.is_dir() else None


def cartella(pacchetto):
    """La cartella dei template di `pacchetto`, se è dentro un modulo attivo e ne ha una; altrimenti None."""
    return _cartella(pacchetto or "", tuple(getattr(settings, "ADDONS_ATTIVI", ())))


def pacchetto_corrente():
    valore = _corrente.get()
    if valore is None:
        return ""
    if isinstance(valore, str):
        return valore
    from .context_processors import tema_della_richiesta
    tema = tema_della_richiesta(valore)
    return (tema or {}).get("template", "")


@contextmanager
def con_pacchetto(pacchetto):
    """Rende i template di `pacchetto` (o nessuno, con ""), qualunque sia la richiesta: es. la favicon di un tema."""
    token = _corrente.set(pacchetto or "")
    try:
        yield
    finally:
        _corrente.reset(token)


class Middleware:
    """Dopo quello dell'azienda corrente: la richiesta va nella ContextVar, il tema si calcola al primo template."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _corrente.set(request)
        try:
            return self.get_response(request)
        finally:
            _corrente.reset(token)


class Loader(LoaderBase):
    """Cerca prima tra i template del tema della richiesta. Ha la sua cache, per (pacchetto, nome): quella standard di
    Django è per nome, e mescolerebbe i temi."""

    def __init__(self, engine):
        super().__init__(engine)
        self._cache = {}

    def get_template(self, template_name, skip=None):
        pacchetto = pacchetto_corrente()
        if not pacchetto:
            raise TemplateDoesNotExist(template_name)
        if skip is not None or settings.DEBUG:
            return super().get_template(template_name, skip)
        chiave = (pacchetto, template_name)
        if chiave not in self._cache:
            try:
                self._cache[chiave] = super().get_template(template_name)
            except TemplateDoesNotExist:
                self._cache[chiave] = None
        if self._cache[chiave] is None:
            raise TemplateDoesNotExist(template_name)
        return self._cache[chiave]

    def get_template_sources(self, template_name):
        radice = cartella(pacchetto_corrente())
        if radice is None:
            return
        try:
            percorso = safe_join(radice, template_name)
        except Exception:                       # nome che esce dalla cartella: non è un template del tema
            return
        yield Origin(name=percorso, template_name=template_name, loader=self)

    def get_contents(self, origin):
        try:
            with open(origin.name, encoding=self.engine.file_charset) as f:
                return f.read()
        except FileNotFoundError:
            raise TemplateDoesNotExist(origin)

    def reset(self):
        self._cache.clear()
