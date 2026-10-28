"""Letto da config/settings.py prima che il framework sia configurato: solo libreria standard."""
import ast
import json
import logging
import re
from pathlib import Path

SCHEMA = 1
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
log = logging.getLogger("core.moduli")


def leggi_stato(addons_dir):
    """Slug nel file di stato, nell'ordine scritto (già topologico). [] se il file manca."""
    percorso = Path(addons_dir) / "installed.json"
    if not percorso.exists():
        return []
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    if dati.get("schema") != SCHEMA:
        raise ValueError(f"{percorso}: schema {dati.get('schema')!r} non supportato (atteso {SCHEMA})")
    return list(dati["installed"])


def _leggibile(addons_dir, slug):
    manifest = Path(addons_dir) / slug / "__manifest__.py"
    if not SLUG_RE.match(slug) or not manifest.is_file():
        return False
    try:
        return isinstance(ast.literal_eval(manifest.read_text(encoding="utf-8")), dict)
    except (SyntaxError, ValueError):
        return False


def moduli_installati(addons_dir, forzati=()):
    """Slug da mettere in INSTALLED_APPS: quelli del file di stato più i `forzati` presenti su disco.
    Un modulo nel file ma assente o con manifest illeggibile viene saltato con un warning, mai un crash."""
    slugs = []
    for slug in leggi_stato(addons_dir):
        if _leggibile(addons_dir, slug):
            slugs.append(slug)
        else:
            log.warning("modulo %r nel file di stato ma assente o illeggibile su disco: saltato", slug)
    for slug in forzati:
        if slug not in slugs and _leggibile(addons_dir, slug):
            slugs.append(slug)
    return slugs
