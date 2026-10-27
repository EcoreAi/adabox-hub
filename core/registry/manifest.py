"""Manifest dei moduli: lettura con ast.literal_eval (mai import) e validazione."""
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from core import __version__

from .bootstrap import SLUG_RE

RISERVATI = {"core", "theme", "config", "admin", "api", "accounts", "static", "media",
             "moduli", "django", "test", "tests"}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
MIN_CORE_RE = re.compile(r"^\d+\.\d+$")
PERM_RE = re.compile(r"^[a-z][a-z0-9_]*\.([a-z_][a-z0-9_]*|\*)$")
DOTTED_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
CHIAVI = {"name", "summary", "version", "author", "category", "depends", "min_core", "application",
          "icon", "menu", "groups", "data", "demo", "hooks", "settings_url"}
OBBLIGATORIE = {"name", "version", "min_core"}
CHIAVI_MENU = {"label", "url_name", "permission"}


class ManifestNonValido(Exception):
    def __init__(self, errori):
        self.errori = list(errori)
        super().__init__("; ".join(self.errori))


@dataclass
class Manifest:
    slug: str
    percorso: Path
    name: str
    version: str
    min_core: str
    summary: str = ""
    author: str = ""
    category: str = ""
    depends: list = field(default_factory=list)
    application: bool = False
    icon: str = ""
    menu: list = field(default_factory=list)
    groups: dict = field(default_factory=dict)
    data: list = field(default_factory=list)
    demo: list = field(default_factory=list)
    hooks: str | None = None
    settings_url: str | None = None


def versione_tupla(v):
    return tuple(int(x) for x in v.split("."))


def core_compatibile(min_core, versione=__version__):
    """Stesso major e minor del kernel >= minor richiesto."""
    mj, mn = (int(x) for x in min_core.split("."))
    cj, cn, *_ = (int(x) for x in versione.split("."))
    return mj == cj and cn >= mn


def leggi(cartella):
    cartella = Path(cartella)
    file = cartella / "__manifest__.py"
    if not file.is_file():
        raise ManifestNonValido([f"{file} non esiste"])
    try:
        dati = ast.literal_eval(file.read_text(encoding="utf-8"))   # mai import: nessun codice eseguito
    except (SyntaxError, ValueError) as e:
        raise ManifestNonValido([f"manifest non è un dizionario letterale: {e}"])
    return valida(dati, cartella.name, cartella)


def _testo(errori, dati, chiave):
    if chiave in dati and not isinstance(dati[chiave], str):
        errori.append(f"{chiave}: atteso testo, trovato {dati[chiave]!r}")


def _file(errori, dati, chiave, cartella):
    valore = dati.get(chiave, [])
    if not isinstance(valore, list):
        errori.append(f"{chiave}: attesa una lista di percorsi, trovato {valore!r}")
        return
    for p in valore:
        if not isinstance(p, str) or PurePosixPath(p).is_absolute() or ".." in PurePosixPath(p).parts:
            errori.append(f"{chiave}: percorso {p!r} non valido (relativo alla cartella del modulo)")
        elif not (Path(cartella) / p).is_file():
            errori.append(f"{chiave}: file {p!r} assente")


def valida(dati, slug, cartella):
    errori = []
    if not isinstance(dati, dict):
        raise ManifestNonValido(["il manifest deve essere un dizionario"])
    if not SLUG_RE.match(slug):
        errori.append(f"slug {slug!r} non valido (atteso ^[a-z][a-z0-9_]{{2,30}}$)")
    if slug in RISERVATI:
        errori.append(f"slug {slug!r} riservato")
    if sconosciute := sorted(set(dati) - CHIAVI):
        errori.append("chiavi sconosciute: " + ", ".join(sconosciute))
    for k in sorted(OBBLIGATORIE - set(dati)):
        errori.append(f"manca la chiave obbligatoria {k!r}")

    for k in ("name", "summary", "author", "category", "icon"):
        _testo(errori, dati, k)
    if "version" in dati and not (isinstance(dati["version"], str) and SEMVER_RE.match(dati["version"])):
        errori.append(f"version: {dati['version']!r} non è nel formato X.Y.Z")
    if "min_core" in dati:
        mc = dati["min_core"]
        if not (isinstance(mc, str) and MIN_CORE_RE.match(mc)):
            errori.append(f"min_core: {mc!r} non è nel formato X.Y")
        elif not core_compatibile(mc):
            errori.append(f"min_core: il modulo chiede il kernel {mc}, installato {__version__}")

    depends = dati.get("depends", [])
    if not isinstance(depends, list):
        errori.append(f"depends: attesa una lista, trovato {depends!r}")
    else:
        for d in depends:
            if not isinstance(d, str) or not SLUG_RE.match(d):
                errori.append(f"depends: {d!r} non è uno slug valido")
            elif d == slug:
                errori.append(f"depends: il modulo {slug!r} non può dipendere da se stesso")

    if "application" in dati and not isinstance(dati["application"], bool):
        errori.append(f"application: atteso True o False, trovato {dati['application']!r}")

    menu = dati.get("menu", [])
    if not isinstance(menu, list):
        errori.append(f"menu: attesa una lista, trovato {menu!r}")
    else:
        for voce in menu:
            if not isinstance(voce, dict):
                errori.append(f"menu: voce {voce!r} non è un dizionario")
                continue
            if extra := sorted(set(voce) - CHIAVI_MENU):
                errori.append(f"menu: voce {voce!r} con chiavi sconosciute: {', '.join(extra)}")
            for k in ("label", "url_name"):
                if not isinstance(voce.get(k), str) or not voce.get(k):
                    errori.append(f"menu: voce {voce!r} senza {k}")
            if "permission" in voce:
                p = voce["permission"]
                if not isinstance(p, str) or not PERM_RE.match(p) or p.endswith("*"):
                    errori.append(f"menu: permission {p!r} non valido (atteso app.codename, senza *)")

    gruppi = dati.get("groups", {})
    if not isinstance(gruppi, dict):
        errori.append(f"groups: atteso un dizionario, trovato {gruppi!r}")
    else:
        for nome, perms in gruppi.items():
            if not isinstance(nome, str) or not nome:
                errori.append(f"groups: nome di gruppo {nome!r} non valido")
            if not isinstance(perms, list):
                errori.append(f"groups: {nome!r} deve avere una lista di permessi, trovato {perms!r}")
                continue
            for p in perms:
                if not isinstance(p, str) or not PERM_RE.match(p):
                    errori.append(f"groups: {nome!r}: permesso {p!r} non valido (atteso app.codename o app.*)")

    _file(errori, dati, "data", cartella)
    _file(errori, dati, "demo", cartella)

    hooks = dati.get("hooks")
    if hooks is not None and not (isinstance(hooks, str) and DOTTED_RE.match(hooks)):
        errori.append(f"hooks: {hooks!r} non è un modulo Python (es. {slug}.hooks)")
    su = dati.get("settings_url")
    if su is not None and not isinstance(su, str):
        errori.append(f"settings_url: atteso testo o None, trovato {su!r}")

    if errori:
        raise ManifestNonValido(errori)
    return Manifest(slug=slug, percorso=Path(cartella), **{k: dati[k] for k in dati})
