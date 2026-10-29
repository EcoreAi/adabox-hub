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
          "icon", "nav_label", "menu", "groups", "data", "demo", "hooks", "ai", "settings_url", "cron", "settings", "sequences",
          "dashboard", "home"}
OBBLIGATORIE = {"name", "version", "min_core"}
CHIAVI_MENU = {"label", "url_name", "permission"}
CHIAVI_CRON = {"nome", "funzione", "ogni", "alle"}
CHIAVI_SETTING = {"chiave", "label", "tipo", "default", "per_azienda", "help", "scelte"}
CHIAVI_SEQUENZA = {"codice", "formato", "azzera"}
TIPI_PARAMETRO = {"testo", "intero", "decimale", "booleano", "scelta", "data"}
OGNI_RE = re.compile(r"^[1-9]\d*[mhd]$")
ALLE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
NOME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CODICE_SEQ_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


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
    nav_label: str = ""                   # etichetta nella barra in alto, se diversa dal nome (es. "Chat")
    menu: list = field(default_factory=list)
    groups: dict = field(default_factory=dict)
    data: list = field(default_factory=list)
    demo: list = field(default_factory=list)
    hooks: str | None = None
    ai: str | None = None                  # modulo con gli strumenti dell'assistente AI (es. "calendario.ai")
    settings_url: str | None = None
    cron: list = field(default_factory=list)
    settings: list = field(default_factory=list)
    sequences: list = field(default_factory=list)
    dashboard: str | None = None
    home: str | None = None


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


def _lista_di_dict(errori, chiave, valore, ammesse):
    if not isinstance(valore, list):
        errori.append(f"{chiave}: attesa una lista, trovato {valore!r}")
        return []
    buone = []
    for voce in valore:
        if not isinstance(voce, dict):
            errori.append(f"{chiave}: voce {voce!r} non è un dizionario")
        elif extra := sorted(set(voce) - ammesse):
            errori.append(f"{chiave}: voce {voce!r} con chiavi sconosciute: {', '.join(extra)}")
        else:
            buone.append(voce)
    return buone


def _unici(errori, chiave, voci, campo):
    visti = set()
    for v in voci:
        if v.get(campo) in visti:
            errori.append(f"{chiave}: {campo} {v.get(campo)!r} ripetuto")
        visti.add(v.get(campo))


def _cron(errori, valore):
    voci = _lista_di_dict(errori, "cron", valore, CHIAVI_CRON)
    for v in voci:
        if not isinstance(v.get("nome"), str) or not v.get("nome"):
            errori.append(f"cron: voce {v!r} senza nome")
        f = v.get("funzione")
        if not (isinstance(f, str) and DOTTED_RE.match(f) and "." in f):
            errori.append(f"cron: funzione {f!r} non valida (atteso modulo.funzione)")
        if not (isinstance(v.get("ogni"), str) and OGNI_RE.match(v["ogni"])):
            errori.append(f"cron: ogni {v.get('ogni')!r} non valido (es. 15m, 1h, 1d)")
        if "alle" in v:
            if not (isinstance(v["alle"], str) and ALLE_RE.match(v["alle"])):
                errori.append(f"cron: alle {v['alle']!r} non valido (atteso HH:MM)")
            elif not str(v.get("ogni", "")).endswith("d"):
                errori.append(f"cron: alle {v['alle']!r} ammesso solo con ogni in giorni (es. 1d)")
    _unici(errori, "cron", voci, "nome")


def _settings(errori, valore):
    voci = _lista_di_dict(errori, "settings", valore, CHIAVI_SETTING)
    for v in voci:
        if not (isinstance(v.get("chiave"), str) and NOME_RE.match(v["chiave"])):
            errori.append(f"settings: chiave {v.get('chiave')!r} non valida")
        if not isinstance(v.get("label"), str) or not v.get("label"):
            errori.append(f"settings: {v.get('chiave')!r} senza label")
        if v.get("tipo") not in TIPI_PARAMETRO:
            errori.append(f"settings: tipo {v.get('tipo')!r} non valido ({', '.join(sorted(TIPI_PARAMETRO))})")
        if v.get("tipo") == "scelta":
            scelte = v.get("scelte")
            if not (isinstance(scelte, list) and scelte and all(
                    isinstance(c, (list, tuple)) and len(c) == 2 for c in scelte)):
                errori.append(f"settings: {v.get('chiave')!r} di tipo scelta senza scelte [[valore, label], ...]")
        if "per_azienda" in v and not isinstance(v["per_azienda"], bool):
            errori.append(f"settings: per_azienda di {v.get('chiave')!r} deve essere True o False")
    _unici(errori, "settings", voci, "chiave")


def _sequenze(errori, valore):
    voci = _lista_di_dict(errori, "sequences", valore, CHIAVI_SEQUENZA)
    for v in voci:
        if not (isinstance(v.get("codice"), str) and CODICE_SEQ_RE.match(v["codice"])):
            errori.append(f"sequences: codice {v.get('codice')!r} non valido (atteso modulo.nome)")
        if not (isinstance(v.get("formato"), str) and "{numero" in v["formato"]):
            errori.append(f"sequences: formato {v.get('formato')!r} senza {{numero}}")
        if v.get("azzera", "mai") not in ("mai", "anno"):
            errori.append(f"sequences: azzera {v.get('azzera')!r} non valido (mai, anno)")
    _unici(errori, "sequences", voci, "codice")


def valida(dati, slug, cartella):
    errori = []
    if not isinstance(dati, dict):
        raise ManifestNonValido(["il manifest deve essere un dizionario"])
    if not SLUG_RE.match(slug):
        errori.append(f"slug {slug!r} non valido (atteso ^[a-z][a-z0-9_]{{1,30}}$)")
    if slug in RISERVATI:
        errori.append(f"slug {slug!r} riservato")
    if sconosciute := sorted(set(dati) - CHIAVI):
        errori.append("chiavi sconosciute: " + ", ".join(sconosciute))
    for k in sorted(OBBLIGATORIE - set(dati)):
        errori.append(f"manca la chiave obbligatoria {k!r}")

    for k in ("name", "summary", "author", "category", "icon", "nav_label"):
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
    _cron(errori, dati.get("cron", []))
    _settings(errori, dati.get("settings", []))
    _sequenze(errori, dati.get("sequences", []))
    dash = dati.get("dashboard")
    if dash is not None and not (isinstance(dash, str) and DOTTED_RE.match(dash) and "." in dash):
        errori.append(f"dashboard: {dash!r} non è una funzione (atteso modulo.funzione)")
    home = dati.get("home")
    if home is not None and not (isinstance(home, str) and ":" in home):
        errori.append(f"home: {home!r} non è un nome URL (atteso app:nome)")

    hooks = dati.get("hooks")
    if hooks is not None and not (isinstance(hooks, str) and DOTTED_RE.match(hooks)):
        errori.append(f"hooks: {hooks!r} non è un modulo Python (es. {slug}.hooks)")
    ai = dati.get("ai")
    if ai is not None and not (isinstance(ai, str) and DOTTED_RE.match(ai) and ai.startswith(f"{slug}.")):
        errori.append(f"ai: {ai!r} non è un modulo Python del modulo stesso (es. {slug}.ai)")
    su = dati.get("settings_url")
    if su is not None and not isinstance(su, str):
        errori.append(f"settings_url: atteso testo o None, trovato {su!r}")

    if errori:
        raise ManifestNonValido(errori)
    return Manifest(slug=slug, percorso=Path(cartella), **{k: dati[k] for k in dati})
