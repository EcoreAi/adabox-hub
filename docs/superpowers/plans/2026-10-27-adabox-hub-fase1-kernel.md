# adabox-hub — piano di implementazione, fase 1: il kernel

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trasformare `core` nel kernel di una piattaforma modulare stile Odoo: app in `addons/` con manifest, installabili, aggiornabili e disinstallabili da riga di comando e dalla pagina `/moduli/`; viste dichiarate in Python (`ModelView`) rese con il theme; multi-azienda; API JSON generica. Un'app di riferimento, `todo`, dimostra che un'app minima si scrive in un giorno senza viste né template propri.

**Architecture:** `theme/` invariato (più HTMX vendorizzato). `core/` è il kernel: `registry/` (manifest, stato, installazione, ricarica, hook), `viste/` (`ModelView` e viste generiche), `api/` (Django Ninja), modelli `Azienda`, `ProfiloUtente`, `Modulo`, `TokenApi`. `addons/<slug>/` sono le app, pacchetti Python con `__manifest__.py`. Lo stato di installazione sta in `addons/installed.json`, letto dai settings per comporre `INSTALLED_APPS`; installare = backup, stato, migrazione in sottoprocesso, ricarica di gunicorn via pidfile.

**Tech Stack:** Python 3.12, Django 5.2, django-environ, django-axes 8, psycopg, gunicorn, **django-ninja**, **Pillow**, **htmx 2** (file vendorizzato); pytest, pytest-django, **pytest-env**.

**Spec:** `docs/superpowers/specs/2026-10-27-adabox-hub-fase1-kernel-design.md`

**Regole per chi esegue:**
- Repo di lavoro: `/opt/adabox-hub`. Venv in `.venv` (`. .venv/bin/activate`); ogni `python`/`pytest` presuppone il venv attivo.
- `/opt/django-template` e `/opt/adaerp` sono **sola lettura** e, per adaerp, **solo come riferimento funzionale**: non si copia codice, template, CSS o testi (LGPL/AGPL). Nessun comando scrive lì.
- Per ogni task: prima i test (falliscono), poi il codice, `pytest` verde su tutta la suite, commit. Commit in italiano, prefisso `feat(core):`, `feat(todo):`, `chore:`, `docs:`, chiusi con `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Nomi: API Python in inglese come Django (`ModelView`, `list_display`), modelli, URL, messaggi e documentazione in italiano.
- Dipendenze nuove si installano con pip e si bloccano in `requirements*.txt` con la versione che `pip freeze` riporta (non si inventano versioni).
- Scostamenti dalla spec decisi qui: (1) la ricarica di gunicorn usa il pidfile (già riportato nella spec); (2) sotto pytest i moduli da caricare si indicano con la variabile `ADDONS_FORCE` letta dai settings, impostata da `pytest-env`, perché il file di stato è per istanza e i test devono girare su un clone pulito; (3) il kernel espone una `ModelView` per `Azienda` (`/core/aziende/`): serve come gestione aziende e come banco di prova delle viste generiche.

---

## Mappa dei file

| File | Responsabilità |
|---|---|
| `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`, `.env.example` | dipendenze, `ADDONS_FORCE`, file ignorati, variabili nuove |
| `conftest.py` | fixture condivise: `utente`, `staff`, `superuser`, `azienda`, `addons_tmp` |
| `core/__init__.py` | `__version__` |
| `core/registry/bootstrap.py` | python puro: `leggi_stato`, `moduli_installati` |
| `core/registry/manifest.py` | `Manifest`, `leggi`, `valida`, `ManifestNonValido`, `core_compatibile` |
| `core/registry/modules.py` | `scopri`, `ordina`, `sincronizza`, `manifests_attivi`, `app_visibili`, `app_corrente` |
| `core/registry/install.py` | `installa`, `aggiorna`, `disinstalla`, `scrivi_stato`, `ApplicaFallita` |
| `core/registry/groups.py` | `espandi`, `crea_gruppi` |
| `core/registry/reload.py` | `richiedi` |
| `core/registry/hooks.py` | `sezione_dettaglio`, `sezioni_per`, `svuota` |
| `core/registry/urls.py` | `patterns_moduli` |
| `core/management/commands/modulo.py` | `lista`, `verifica`, `sincronizza`, `installa`, `aggiorna`, `disinstalla` |
| `core/management/commands/_modulo_applica.py` | passi che girano nel sottoprocesso |
| `core/backup.py` | `esegui`, `pulisci`, `BackupFallito` |
| `core/models.py`, `core/mixins.py`, `core/signals.py` | `Azienda`, `ProfiloUtente`, `Modulo`, `TokenApi`, `AziendaMixin` |
| `core/middleware.py` | `AziendaCorrenteMiddleware` |
| `core/context_processors.py` | `piattaforma` |
| `core/viste/base.py`, `registry.py`, `lista.py`, `form.py`, `dettaglio.py`, `elimina.py`, `azioni.py`, `filtri.py`, `widgets.py` | `ModelView` e viste generiche |
| `core/templatetags/vista.py` | `{% campo %}`, `{% cella %}`, `{% querystring_con %}` |
| `core/templates/core/base_app.html`, `partials/_menu_app.html`, `partials/_aziende.html` | shell delle app |
| `core/templates/core/vista/*.html` | lista, tabella, form, campo, dettaglio, conferma |
| `core/templates/core/launcher.html`, `moduli.html`, `partials/_moduli_stato.html`, `stile.html`, `profilo.html` | pagine del kernel |
| `core/api/__init__.py`, `core/api/fissi.py`, `core/api/modelli.py` | API |
| `core/views.py`, `core/urls.py`, `core/admin.py`, `core/forms.py` | pagine del kernel, `AziendaView` |
| `theme/static/theme/vendor/htmx.min.js`, `theme/templates/theme/base.html` | HTMX |
| `config/settings.py`, `config/urls.py` | addons, media, backup, reload, API, moduli montati |
| `addons/todo/*` | app di riferimento |
| `deploy/entrypoint.sh`, `Dockerfile`, `docker-compose.yml`, `README.md` | deploy e documentazione |

---

### Task 0: primo commit del clone

Il repo è stato clonato da `django-template` e non ha ancora commit.

- [ ] **Step 1: commit dello stato attuale**

```bash
git add -A && git status --short | wc -l
git commit -m "chore: clone di django-template come adabox-hub

Brand Adabox Hub, docker-compose rinominato (porta 8096), test del brand
letti da settings.THEME, spec della fase 1.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 1: Impianto — dipendenze, versione, addons, bootstrap, settings, HTMX

**Files:**
- Modify: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.gitignore`, `.env.example`
- Create: `addons/.gitkeep`, `backup/.gitkeep`, `conftest.py`
- Create: `core/registry/__init__.py` (vuoto), `core/registry/bootstrap.py`
- Modify: `core/__init__.py`, `config/settings.py`
- Create: `theme/static/theme/vendor/htmx.min.js`; modify `theme/templates/theme/base.html`
- Test: `core/tests/test_bootstrap.py`, `theme/tests/test_base.py` (aggiunta), `config/tests/test_settings.py` (aggiunta)

- [ ] **Step 1: dipendenze**

```bash
pip install django-ninja Pillow pytest-env
pip freeze | grep -i -E "^(django-ninja|pillow|pytest-env)=="
```
Aggiungi le tre righe con la versione stampata: `django-ninja` e `Pillow` in `requirements.txt`, `pytest-env` in `requirements-dev.txt`.

- [ ] **Step 2: HTMX vendorizzato**

```bash
mkdir -p theme/static/theme/vendor
curl -fsSL -o theme/static/theme/vendor/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
head -c 200 theme/static/theme/vendor/htmx.min.js
```
Se la 2.0.4 non è disponibile, usa l'ultima della serie 2.0 e scrivi la versione scelta nel commit. In `theme/templates/theme/base.html`, prima di `ui.js`:
```django
  <script src="{% static 'theme/vendor/htmx.min.js' %}" defer></script>
```

- [ ] **Step 3: test (falliscono)**

`core/tests/test_bootstrap.py`:
```python
import json
from pathlib import Path

from core.registry import bootstrap


def _stato(cartella, slugs):
    (cartella / "installed.json").write_text(json.dumps({"schema": 1, "installed": slugs}))


def _modulo(cartella, slug, manifest="{'name': 'X', 'version': '1.0.0', 'min_core': '1.0'}"):
    (cartella / slug).mkdir()
    (cartella / slug / "__manifest__.py").write_text(manifest)


def test_senza_file_nessun_modulo(tmp_path):
    assert bootstrap.moduli_installati(tmp_path) == []


def test_ordine_conservato(tmp_path):
    _modulo(tmp_path, "beta"); _modulo(tmp_path, "alfa")
    _stato(tmp_path, ["beta", "alfa"])
    assert bootstrap.moduli_installati(tmp_path) == ["beta", "alfa"]


def test_modulo_assente_saltato_con_warning(tmp_path, caplog):
    _modulo(tmp_path, "alfa")
    _stato(tmp_path, ["alfa", "fantasma"])
    assert bootstrap.moduli_installati(tmp_path) == ["alfa"]
    assert "fantasma" in caplog.text


def test_manifest_rotto_saltato(tmp_path, caplog):
    _modulo(tmp_path, "rotto", manifest="{'name': __import__('os')}")
    _stato(tmp_path, ["rotto"])
    assert bootstrap.moduli_installati(tmp_path) == []
    assert "rotto" in caplog.text


def test_forzati_aggiunti_se_presenti(tmp_path):
    _modulo(tmp_path, "alfa"); _modulo(tmp_path, "beta")
    _stato(tmp_path, ["alfa"])
    assert bootstrap.moduli_installati(tmp_path, forzati=["beta", "alfa", "nessuno"]) == ["alfa", "beta"]


def test_schema_sconosciuto(tmp_path):
    (tmp_path / "installed.json").write_text('{"schema": 99, "installed": []}')
    import pytest
    with pytest.raises(ValueError):
        bootstrap.moduli_installati(tmp_path)


def test_non_importa_django():
    sorgente = Path(bootstrap.__file__).read_text()
    assert "django" not in sorgente.lower()
```

In `theme/tests/test_base.py` aggiungi:
```python
def test_base_carica_htmx(client, django_user_model):
    u = django_user_model.objects.create_user("u", "u@example.com", "pass12345!")
    client.force_login(u)
    r = client.get("/")
    assert "theme/vendor/htmx.min.js" in r.content.decode()
```

In `config/tests/test_settings.py` aggiungi un test che carica i settings con `runpy` (come gli altri del file) con `ADDONS_DIR` puntato a una cartella temporanea che contiene un modulo `alfa` e `installed.json` con `["alfa"]`, e verifica `"alfa" in INSTALLED_APPS`, `ADDONS_ATTIVI == ["alfa"]`, `str(ADDONS_DIR) in sys.path`.

Run: `pytest core/tests/test_bootstrap.py theme/tests/test_base.py config/tests/test_settings.py -v`
Expected: FAIL (`ModuleNotFoundError: core.registry`).

- [ ] **Step 4: versione e bootstrap**

`core/__init__.py`:
```python
__version__ = "1.0.0"
```

`core/registry/bootstrap.py` (nessun import da Django: lo leggono i settings):
```python
"""Letto da config/settings.py prima che Django sia configurato: solo libreria standard."""
import ast
import json
import logging
import re
from pathlib import Path

SCHEMA = 1
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
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
```

- [ ] **Step 5: settings**

In `config/settings.py`, dopo `BASE_DIR` ed `env`:
```python
import sys
from core import __version__ as CORE_VERSION          # core/__init__.py non importa Django
from core.registry import bootstrap

ADDONS_DIR = Path(env("ADDONS_DIR", default=str(BASE_DIR / "addons")))
if str(ADDONS_DIR) not in sys.path:
    sys.path.insert(0, str(ADDONS_DIR))
ADDONS_ATTIVI = bootstrap.moduli_installati(ADDONS_DIR, forzati=env.list("ADDONS_FORCE", default=[]))
```
`INSTALLED_APPS`: aggiungi `"ninja"` dopo `"axes"`, e in coda `*ADDONS_ATTIVI`. Poi:
```python
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
BACKUP_DIR = Path(env("BACKUP_DIR", default=str(BASE_DIR / "backup")))
BACKUP_CONSERVA = env.int("BACKUP_CONSERVA", default=10)
RELOAD_STRATEGY = env("RELOAD_STRATEGY", default="runserver" if DEBUG else "gunicorn")
GUNICORN_PIDFILE = env("GUNICORN_PIDFILE", default="/tmp/gunicorn.pid")
```
Logging: aggiungi sempre (anche con `DEBUG=True`) un handler `RotatingFileHandler` su `logs/moduli.log` per il logger `core.moduli` (INFO, propaga alla console).

`pytest.ini`:
```ini
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = test_*.py
env =
    ADDONS_FORCE=todo
```
(`todo` non esiste ancora: `moduli_installati` lo ignora finché non c'è.)

`.gitignore`: aggiungi `addons/installed.json`, `backup/*`, `!backup/.gitkeep`, `media/`. `.env.example`: aggiungi, commentate, `ADDONS_DIR`, `BACKUP_DIR`, `BACKUP_CONSERVA`, `RELOAD_STRATEGY` (`gunicorn|runserver|none`), `GUNICORN_PIDFILE`.

- [ ] **Step 6: conftest condiviso**

`conftest.py` (radice; sposta qui la fixture `staff` da `core/tests/test_pagine.py`):
```python
import textwrap

import pytest
from django.contrib.auth.models import User


@pytest.fixture
def utente(db):
    return User.objects.create_user("mario", "mario@example.com", "pass12345!")


@pytest.fixture
def staff(db, client):
    u = User.objects.create_user("staff", "staff@example.com", "pass12345!", is_staff=True)
    client.force_login(u)
    return u


@pytest.fixture
def superuser(db, client):
    u = User.objects.create_superuser("root", "root@example.com", "pass12345!")
    client.force_login(u)
    return u


class _Addons:
    """Cartella addons temporanea con una factory di moduli finti (manifest, apps, models, migrations)."""

    def __init__(self, cartella):
        self.dir = cartella

    def crea(self, slug, modelli="", **extra):
        manifest = {"name": slug.title(), "version": "1.0.0", "min_core": "1.0", **extra}
        d = self.dir / slug
        (d / "migrations").mkdir(parents=True)
        (d / "migrations" / "__init__.py").write_text("")
        (d / "__init__.py").write_text("")
        (d / "__manifest__.py").write_text(repr(manifest))
        (d / "apps.py").write_text(textwrap.dedent(f"""
            from django.apps import AppConfig


            class Config(AppConfig):
                name = "{slug}"
        """))
        (d / "models.py").write_text("from django.db import models\n" + textwrap.dedent(modelli))
        return d


@pytest.fixture
def addons_tmp(tmp_path, settings, monkeypatch):
    cartella = tmp_path / "addons"
    cartella.mkdir()
    settings.ADDONS_DIR = cartella
    monkeypatch.syspath_prepend(str(cartella))
    return _Addons(cartella)
```

Run: `pytest -v`
Expected: tutto verde (i test di Task 1 inclusi; i test di `core/tests/test_pagine.py` usano la fixture spostata).

- [ ] **Step 7: commit**

```bash
git add -A && git commit -m "feat(core): impianto del kernel: addons, bootstrap dello stato, ninja, htmx vendorizzato

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Manifest — schema, validazione, comando `verifica`

**Files:**
- Create: `core/registry/manifest.py`, `core/management/__init__.py`, `core/management/commands/__init__.py`, `core/management/commands/modulo.py`
- Test: `core/tests/test_manifest.py`

- [ ] **Step 1: test (falliscono)**

`core/tests/test_manifest.py`, casi (ognuno un test, usa `addons_tmp.crea`):
- manifest minimo valido → `leggi(cartella)` restituisce `Manifest` con `slug`, `name`, `version`, `depends == []`, `application is False`;
- chiave sconosciuta (`"nome": "x"`) → `ManifestNonValido` e il messaggio contiene `nome`;
- manca `min_core` → errore che cita `min_core`;
- `version = "1.0"` → errore "X.Y.Z";
- `min_core = "9.0"` → errore che cita `9.0` e `core.__version__`;
- slug riservato (`addons_tmp.crea("admin")`) → errore;
- slug non valido (`"Alfa-1"`) → errore;
- `depends = ["Alfa"]` → errore (slug di dipendenza non valido);
- `groups = {"G": ["todo.view_x", "todo.*"]}` valido; `{"G": ["view_x"]}` → errore (manca l'app);
- `menu = [{"label": "A"}]` → errore (manca `url_name`); `permission` con `*` → errore;
- `data = ["data/x.json"]` con file assente → errore; con file presente → ok;
- manifest con codice (`{'name': __import__('os').getcwd()}`) → `ManifestNonValido`, e `os.getcwd` non viene chiamato (monkeypatch che fallirebbe);
- `core_compatibile("1.0", "1.4.2")` vero, `("1.5", "1.4.2")` falso, `("1.0", "2.0.0")` falso (major diverso);
- `python manage.py modulo verifica <cartella>` → exit 0 e stampa "OK" per un manifest valido; exit 1 con l'elenco degli errori altrimenti (`call_command` con `CommandError`).

Run: `pytest core/tests/test_manifest.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 2: manifest.py**

```python
import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from core import __version__
from .bootstrap import SLUG_RE

RISERVATI = {"core", "theme", "config", "admin", "api", "accounts", "static", "media",
             "moduli", "django", "test", "tests"}
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
MIN_CORE_RE = re.compile(r"^\d+\.\d+$")
PERM_RE = re.compile(r"^[a-z][a-z0-9_]*\.([a-z_][a-z0-9_]*|\*)$")
CHIAVI = {"name", "summary", "version", "author", "category", "depends", "min_core", "application",
          "icon", "menu", "groups", "data", "demo", "hooks", "settings_url"}
OBBLIGATORIE = {"name", "version", "min_core"}


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
    # ... un controllo per chiave, ciascuno appende a `errori`:
    #  name/summary/author/category/icon: str;  version: SEMVER_RE;  min_core: MIN_CORE_RE e core_compatibile;
    #  depends: list di slug validi e != slug;  application: bool;
    #  menu: list di dict con label e url_name str, permission str PERM_RE senza '*', nessun'altra chiave;
    #  groups: dict str -> list di str PERM_RE;  data/demo: list di str relativi, file esistenti sotto cartella;
    #  hooks: str punteggiata o None;  settings_url: str o None.
    if errori:
        raise ManifestNonValido(errori)
    return Manifest(slug=slug, percorso=Path(cartella), **{k: dati[k] for k in dati})
```
Scrivi per esteso i controlli indicati nel commento; ogni messaggio nomina la chiave e il valore sbagliato.

- [ ] **Step 3: comando `modulo` con il sottocomando `verifica`**

`core/management/commands/modulo.py`: `BaseCommand` con `add_arguments` che crea `subparsers` (`dest="sottocomando"`, `required=True`). In questo task solo `verifica <percorso>`: chiama `manifest.leggi`, stampa `OK <slug> <version>` oppure solleva `CommandError` con gli errori uno per riga. I sottocomandi successivi (`lista`, `sincronizza`, `installa`, `aggiorna`, `disinstalla`) si aggiungono nei task 5 e 7 allo stesso file.

Run: `pytest core/tests/test_manifest.py -v`
Expected: tutti passed.

- [ ] **Step 4: commit** — `feat(core): manifest dei moduli con validazione e comando modulo verifica`

---

### Task 3: Modelli del kernel — Azienda, ProfiloUtente, AziendaMixin, Modulo, TokenApi; via Cliente

**Files:**
- Modify: `core/models.py`, `core/admin.py`, `core/views.py`, `core/urls.py`, `core/apps.py`, `core/forms.py`
- Create: `core/mixins.py`, `core/signals.py`, `core/migrations/0002_kernel.py`, `core/migrations/0003_azienda_iniziale.py`
- Modify: `core/templates/core/home.html` (segnaposto), `core/tests/test_pagine.py`
- Test: `core/tests/test_modelli.py`

- [ ] **Step 1: test (falliscono)**

`core/tests/test_modelli.py`:
- `Azienda.objects.get(pk=1).nome == settings.THEME["brand"]` (creata dalla migrazione);
- creare un `User` crea il `ProfiloUtente` con `aziende` = tutte le attive e `azienda_predefinita` = la prima;
- `TokenApi.genera(utente, "cli")` restituisce `(token, chiaro)`; `chiaro` non è salvato (`token.chiave != chiaro`); `TokenApi.verifica(chiaro) == token` e aggiorna `ultimo_uso`; `verifica("x")` è `None`; token disattivato → `None`;
- `Modulo` ha i choices di stato `disponibile, installato, da_aggiornare, mancante, errore`;
- `AziendaMixin` è astratto (`AziendaMixin._meta.abstract`), con campo `azienda` FK `PROTECT`;
- `core.models.Cliente` non esiste più (`hasattr(models, "Cliente") is False`).

In `core/tests/test_pagine.py` togli i test sui KPI e sui clienti; resta: home → 200 da staff, 302 da anonimo; stile e profilo → 200.

Run: `pytest core/tests -v` — Expected: FAIL.

- [ ] **Step 2: modelli**

`core/mixins.py`:
```python
from django.db import models


class AziendaMixin(models.Model):
    azienda = models.ForeignKey("core.Azienda", on_delete=models.PROTECT, verbose_name="azienda")

    class Meta:
        abstract = True
        indexes = [models.Index(fields=["azienda"])]
```

`core/models.py` (sostituisce `Cliente`):
```python
import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class Azienda(models.Model):
    nome = models.CharField("nome", max_length=160)
    partita_iva = models.CharField("partita IVA", max_length=16, blank=True)
    codice_fiscale = models.CharField("codice fiscale", max_length=16, blank=True)
    indirizzo = models.CharField("indirizzo", max_length=200, blank=True)
    cap = models.CharField("CAP", max_length=10, blank=True)
    citta = models.CharField("città", max_length=100, blank=True)
    provincia = models.CharField("provincia", max_length=2, blank=True)
    email = models.EmailField("email", blank=True)
    telefono = models.CharField("telefono", max_length=40, blank=True)
    logo = models.ImageField("logo", upload_to="aziende/", blank=True)
    attiva = models.BooleanField("attiva", default=True)

    class Meta:
        verbose_name = "azienda"
        verbose_name_plural = "aziende"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class ProfiloUtente(models.Model):
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profilo")
    aziende = models.ManyToManyField(Azienda, verbose_name="aziende consentite", blank=True)
    azienda_predefinita = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name="+", verbose_name="azienda predefinita")

    class Meta:
        verbose_name = "profilo utente"
        verbose_name_plural = "profili utente"

    def __str__(self):
        return f"profilo di {self.utente}"


class Modulo(models.Model):
    DISPONIBILE, INSTALLATO, DA_AGGIORNARE, MANCANTE, ERRORE = (
        "disponibile", "installato", "da_aggiornare", "mancante", "errore")
    STATI = [(DISPONIBILE, "Disponibile"), (INSTALLATO, "Installato"), (DA_AGGIORNARE, "Da aggiornare"),
             (MANCANTE, "Mancante"), (ERRORE, "Errore")]
    slug = models.SlugField("slug", max_length=31, unique=True)
    nome = models.CharField("nome", max_length=120)
    versione_installata = models.CharField("versione installata", max_length=20, blank=True)
    versione_disponibile = models.CharField("versione disponibile", max_length=20, blank=True)
    stato = models.CharField("stato", max_length=20, choices=STATI, default=DISPONIBILE)
    application = models.BooleanField("app", default=False)
    installato_il = models.DateTimeField("installato il", null=True, blank=True)
    aggiornato_il = models.DateTimeField("aggiornato il", null=True, blank=True)
    gruppi_creati = models.JSONField("gruppi creati", default=list, blank=True)
    ultimo_errore = models.TextField("ultimo errore", blank=True)

    class Meta:
        verbose_name = "modulo"
        verbose_name_plural = "moduli"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.slug})"


class TokenApi(models.Model):
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="token_api")
    nome = models.CharField("nome", max_length=80)
    chiave = models.CharField("chiave (hash)", max_length=64, unique=True, editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    ultimo_uso = models.DateTimeField("ultimo uso", null=True, blank=True)
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "token API"
        verbose_name_plural = "token API"

    @staticmethod
    def _hash(chiaro):
        return hashlib.sha256(chiaro.encode()).hexdigest()

    @classmethod
    def genera(cls, utente, nome):
        chiaro = secrets.token_urlsafe(32)
        return cls.objects.create(utente=utente, nome=nome, chiave=cls._hash(chiaro)), chiaro

    @classmethod
    def verifica(cls, chiaro):
        token = cls.objects.filter(chiave=cls._hash(chiaro), attivo=True, utente__is_active=True).select_related("utente").first()
        if token:
            cls.objects.filter(pk=token.pk).update(ultimo_uso=timezone.now())
        return token
```

`core/signals.py`: `post_save` su `User` → se `created`, crea `ProfiloUtente`, aggiunge le `Azienda` attive, imposta la predefinita (la prima per `nome`). Collegato in `CoreConfig.ready()`.

- [ ] **Step 3: migrazioni**

```bash
python manage.py makemigrations core -n kernel
```
Verifica che `0002_kernel.py` contenga `DeleteModel("Cliente")` e i quattro modelli. Poi `0003_azienda_iniziale.py` a mano: `RunPython` che crea `Azienda(pk=1, nome=settings.THEME.get("brand", "Azienda"))` se non ce n'è nessuna, con `noop` inverso. I profili per gli utenti già esistenti li crea la stessa migrazione (ciclo su `User`).

- [ ] **Step 4: admin, home segnaposto, forms**

`core/admin.py`: registra `Azienda` (list_display nome, partita_iva, citta, attiva; search nome, partita_iva) e `ProfiloUtente` (filter_horizontal aziende). `Modulo` e `TokenApi` si registrano nei task 11 e 12. `core/views.py`: `home` rende `core/home.html` con solo il page head "Benvenuto" (il launcher arriva in Task 10). `core/forms.py`: solo `ProfiloForm`.

Run: `pytest -v` — Expected: tutto verde.

- [ ] **Step 5: commit** — `feat(core): modelli del kernel (Azienda, ProfiloUtente, Modulo, TokenApi) e rimozione dell'esempio Cliente`

---

### Task 4: Azienda corrente — middleware, cambio azienda, selettore

**Files:**
- Create: `core/middleware.py`, `core/azienda.py`, `core/templates/core/partials/_aziende.html`
- Modify: `config/settings.py` (MIDDLEWARE), `core/views.py`, `core/urls.py`
- Test: `core/tests/test_azienda.py`

- [ ] **Step 1: test (falliscono)**

- utente anonimo → `request.azienda is None` (vista di prova con `RequestFactory` + middleware);
- utente con profilo → `request.azienda == azienda_predefinita`;
- `POST core:cambia_azienda {"azienda": pk}` con pk consentita → 302 al `next` (o `/`), sessione aggiornata, richiesta successiva ha quella azienda;
- pk non consentita → 403; pk inesistente → 404; GET → 405;
- `_aziende.html` (render del partial con un contesto) mostra il selettore solo con più di un'azienda.

- [ ] **Step 2: implementazione**

`core/azienda.py`:
```python
CHIAVE_SESSIONE = "azienda_id"


def consentite(user):
    if not user.is_authenticated:
        return []
    profilo = getattr(user, "profilo", None)
    return list(profilo.aziende.filter(attiva=True)) if profilo else []


def corrente(request):
    aziende = consentite(request.user)
    if not aziende:
        return None
    pk = request.session.get(CHIAVE_SESSIONE)
    for a in aziende:
        if a.pk == pk:
            return a
    predefinita = request.user.profilo.azienda_predefinita
    return predefinita if predefinita in aziende else aziende[0]
```
`core/middleware.py`: `AziendaCorrenteMiddleware` imposta `request.azienda = SimpleLazyObject(lambda: corrente(request))` (lazy: niente query se la pagina non la usa) e, per l'anonimo, `None`. In `MIDDLEWARE` dopo `AuthenticationMiddleware`. Vista `cambia_azienda` (`POST`, `login_required`): valida, scrive in sessione, `messages.success`, redirect a `next` se sicuro (`url_has_allowed_host_and_scheme`) altrimenti `/`. URL `core:cambia_azienda` = `azienda/cambia/`. Partial `_aziende.html`: `<form method="post">` con `<select class="ui-select" name="azienda" onchange="this.form.submit()">` e il `csrf_token`; mostrato solo se `aziende|length > 1`.

Run: `pytest core/tests/test_azienda.py -v` — Expected: passed.

- [ ] **Step 3: commit** — `feat(core): azienda corrente in sessione, cambio azienda e selettore`

---

### Task 5: Registro — scoperta, ordinamento, stati, sincronizzazione, `lista`

**Files:**
- Create: `core/registry/modules.py`
- Modify: `core/management/commands/modulo.py` (`lista`, `sincronizza`)
- Test: `core/tests/test_registry.py`

- [ ] **Step 1: test (falliscono)**

Con `addons_tmp`:
- `scopri()` trova i moduli con manifest valido e include quelli con manifest rotto con `errore` valorizzato e `manifest None`; ignora cartelle senza `__manifest__.py` e file;
- `ordina(["crm", "contatti"], info)` con `crm.depends = ["contatti"]` → `["contatti", "crm"]`; dipendenza assente → `ManifestNonValido` che la nomina; ciclo → `ManifestNonValido` con "ciclo";
- `sincronizza()`: modulo su disco non nel file → riga `disponibile` con `versione_disponibile`; nel file e su disco con stessa versione → `installato`; nel file con manifest `version` maggiore della `versione_installata` → `da_aggiornare`; nel file ma cartella assente → `mancante` (la riga resta, `nome` conservato); riga con stato `errore` resta `errore` finché un comando non la cambia; una riga di un modulo sparito dal disco e non nel file viene cancellata;
- `manage.py modulo lista` stampa una riga per modulo con slug, versione installata, disponibile e stato.

- [ ] **Step 2: modules.py**

```python
@dataclass
class InfoModulo:
    slug: str
    cartella: Path
    manifest: Manifest | None = None
    errore: str | None = None


def scopri(addons_dir=None) -> dict[str, InfoModulo]:
    """Tutte le cartelle di ADDONS_DIR con un __manifest__.py, valido o no."""


def ordina(slugs, info) -> list[str]:
    """Ordine topologico (Kahn) sui depends; stabile per nome a parità. Errore se dipendenza assente o ciclo."""


def installati() -> list[str]:
    return bootstrap.leggi_stato(settings.ADDONS_DIR)


def sincronizza() -> list[Modulo]:
    """Allinea le righe Modulo a disco + file di stato; restituisce le righe ordinate per nome."""


def manifests_attivi() -> dict[str, Manifest]:
    """Manifest dei moduli in settings.ADDONS_ATTIVI (cache per processo: non cambiano senza riavvio)."""
```
`app_visibili` e `app_corrente` si aggiungono in Task 10. `lista` e `sincronizza` nel comando usano `sincronizza()` e stampano con larghezze fisse.

Run: `pytest core/tests/test_registry.py -v` — Expected: passed.

- [ ] **Step 3: commit** — `feat(core): registro dei moduli: scoperta, ordinamento per dipendenze, stati e sincronizzazione`

---

### Task 6: Backup del database

**Files:**
- Create: `core/backup.py`
- Test: `core/tests/test_backup.py`

- [ ] **Step 1: test (falliscono)**

- con il DB di test (sqlite): `esegui("prova")` crea `BACKUP_DIR/<AAAA-MM-GG-HHMMSS>-prova.sqlite3` (settings `BACKUP_DIR` = `tmp_path`) apribile con `sqlite3` e contenente la tabella `core_azienda`;
- Postgres (monkeypatch di `settings.DATABASES["default"]["ENGINE"]` e di `subprocess.run`): viene chiamato `pg_dump` con `-Fc`, `--dbname` composto da host, porta, utente e nome, `PGPASSWORD` nell'env e `--file` nel `BACKUP_DIR`; `returncode != 0` → `BackupFallito` con lo stderr;
- `pulisci()` tiene solo gli ultimi `BACKUP_CONSERVA` file (per nome, che inizia con la data);
- `esegui` su un engine sconosciuto → `BackupFallito`.

- [ ] **Step 2: backup.py**

`esegui(motivo)`: crea `BACKUP_DIR`, sceglie per engine: `sqlite3` → `connection.connection.backup(sqlite3.connect(dest))` (API nativa di sqlite, funziona anche sul DB in memoria dei test); `postgresql` → `subprocess.run(["pg_dump", "-Fc", "--dbname", url, "--file", dest], env={**os.environ, "PGPASSWORD": pw}, capture_output=True, text=True)`. Poi `pulisci()`. Log su `core.moduli`. Restituisce il `Path`.

Run: `pytest core/tests/test_backup.py -v` — Expected: passed.

- [ ] **Step 3: commit** — `feat(core): backup del database prima di installazioni e aggiornamenti`

---

### Task 7: Installazione, aggiornamento, disinstallazione, gruppi, hook, ricarica

**Files:**
- Create: `core/registry/install.py`, `core/registry/groups.py`, `core/registry/reload.py`, `core/management/commands/_modulo_applica.py`
- Modify: `core/management/commands/modulo.py` (`installa`, `aggiorna`, `disinstalla`)
- Test: `core/tests/test_groups.py`, `core/tests/test_reload.py`, `core/tests/test_install.py`

- [ ] **Step 1: test (falliscono)**

`test_groups.py` (usa i permessi reali di `core`):
- `espandi("core.*")` → tutti i codename dei modelli di `core` con prefisso `core.`; `espandi("core.view_azienda")` → `["core.view_azienda"]`; permesso inesistente → `ValueError`;
- `crea_gruppi(manifest)` con `groups={"Prova / Utente": ["core.view_azienda"], "Prova / Capo": ["core.*"]}` crea i due gruppi con i permessi giusti e restituisce i nomi; richiamata con un permesso in meno lo toglie (riallineamento idempotente).

`test_reload.py`:
- `RELOAD_STRATEGY="none"` → `richiedi()` è `False` e non chiama `os.kill`;
- `"gunicorn"` con pidfile in `tmp_path` contenente `4242` → `os.kill(4242, signal.SIGHUP)` (monkeypatch); pidfile assente → `RicaricaNonDisponibile`;
- `"runserver"` → aggiorna l'mtime di `config/settings.py` (monkeypatch di `os.utime`, verifica del percorso);
- strategia sconosciuta → `ValueError`.

`test_install.py` (con `addons_tmp`, `settings.BACKUP_DIR = tmp_path/"backup"`, e `_applica` sostituito da un finto che registra le chiamate, salvo dove indicato):
- `installa(["crm"])` con `crm.depends=["contatti"]` e `contatti` non installato: con `conferma` che restituisce `True` → file di stato `["contatti", "crm"]`, un backup creato, `_applica("installa", ["contatti", "crm"], demo=False)`; con `conferma` che restituisce `False` → niente scritto;
- modulo già installato → `GiaInstallato` (nessun backup);
- `min_core` troppo alta → `ManifestNonValido`, nessun backup;
- `_applica` che solleva `ApplicaFallita("boom")` → file di stato ripristinato al precedente, riga `Modulo` in `errore` con "boom", l'eccezione risale;
- backup che fallisce (`monkeypatch` di `backup.esegui`) → niente scritto, `BackupFallito` risale;
- `scrivi_stato` è atomica: dopo la scrittura non restano file temporanei e il contenuto è `{"schema": 1, "installed": [...]}`;
- `disinstalla("contatti")` con `crm` installato che dipende da `contatti` → `DipendentiInstallati` che nomina `crm`;
- `disinstalla("crm")` → `_applica("disinstalla", ["crm"], elimina_dati=False)` chiamata **prima** di riscrivere lo stato senza `crm`;
- `aggiorna(["crm"])` con riga `da_aggiornare` → backup, `_applica("aggiorna", ["crm"])`; con riga `installato` e stessa versione → `NienteDaAggiornare`;
- `--riavvia` → `reload.richiedi` chiamato (monkeypatch) solo a fine operazione riuscita;
- `_modulo_applica installa <slug>` **in-process** su un modulo finto che è già in `INSTALLED_APPS`: per testarlo, `addons_tmp.crea("alfa", modelli=...)` con un modello e una migrazione generata (`call_command("makemigrations", "alfa")`), poi `settings.INSTALLED_APPS += ["alfa"]` e `apps.set_installed_apps`... **troppo fragile**: il flusso completo nel sottoprocesso si verifica end-to-end in Task 13 (`test_installazione.py` di `todo`). Qui si testano solo le funzioni di supporto di `_modulo_applica`: `carica_fixture(manifest, demo)` chiama `loaddata` con i percorsi assoluti; `esegui_hook(manifest, "post_install", modulo)` importa il modulo indicato e chiama la funzione se esiste, ignora se manca; `aggiorna_riga(manifest, stato=...)` scrive la riga `Modulo`.

- [ ] **Step 2: groups.py, reload.py**

```python
# core/registry/groups.py
def espandi(perm):
    app, codename = perm.split(".", 1)
    qs = Permission.objects.filter(content_type__app_label=app)
    if codename != "*":
        qs = qs.filter(codename=codename)
    trovati = [f"{app}.{p.codename}" for p in qs]
    if not trovati:
        raise ValueError(f"permesso {perm!r} inesistente")
    return trovati


def crea_gruppi(manifest):
    """Crea o riallinea i gruppi del manifest. Restituisce i nomi (vanno in Modulo.gruppi_creati)."""
    nomi = []
    for nome, perms in manifest.groups.items():
        gruppo, _ = Group.objects.get_or_create(name=nome)
        codici = {p for perm in perms for p in espandi(perm)}
        gruppo.permissions.set(Permission.objects.filter(
            Q(*[Q(content_type__app_label=a, codename=c) for a, c in (p.split(".", 1) for p in codici)], _connector=Q.OR)))
        nomi.append(nome)
    return nomi
```

```python
# core/registry/reload.py
import os
import signal
from pathlib import Path

from django.conf import settings


class RicaricaNonDisponibile(Exception):
    pass


def richiedi():
    """Chiede al server di ricaricare il codice. True se ha fatto qualcosa."""
    strategia = settings.RELOAD_STRATEGY
    if strategia == "none":
        return False
    if strategia == "gunicorn":
        pidfile = Path(settings.GUNICORN_PIDFILE)
        if not pidfile.is_file():
            raise RicaricaNonDisponibile(f"pidfile {pidfile} assente: riavvia gunicorn a mano")
        os.kill(int(pidfile.read_text().strip()), signal.SIGHUP)
        return True
    if strategia == "runserver":
        os.utime(Path(settings.BASE_DIR) / "config" / "settings.py")   # lo StatReloader riavvia
        return True
    raise ValueError(f"RELOAD_STRATEGY {strategia!r} sconosciuta")
```

- [ ] **Step 3: install.py**

```python
class ErroreInstallazione(Exception): ...
class GiaInstallato(ErroreInstallazione): ...
class NienteDaAggiornare(ErroreInstallazione): ...
class DipendentiInstallati(ErroreInstallazione): ...
class ApplicaFallita(ErroreInstallazione): ...


def scrivi_stato(slugs):
    percorso = Path(settings.ADDONS_DIR) / "installed.json"
    tmp = percorso.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": bootstrap.SCHEMA, "installed": list(slugs)}, indent=2) + "\n")
    os.replace(tmp, percorso)


def _applica(operazione, slugs, **opzioni):
    """Esegue `manage.py _modulo_applica <operazione> <slugs>` in un processo nuovo, che legge
    il file di stato aggiornato e quindi ha i moduli in INSTALLED_APPS. Log in logs/moduli.log."""
    cmd = [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "_modulo_applica", operazione, *slugs]
    if opzioni.get("demo"): cmd.append("--demo")
    if opzioni.get("elimina_dati"): cmd.append("--elimina-dati")
    esito = subprocess.run(cmd, cwd=settings.BASE_DIR, capture_output=True, text=True)
    log.info("%s %s:\n%s", operazione, " ".join(slugs), esito.stdout)
    if esito.returncode != 0:
        raise ApplicaFallita((esito.stderr or esito.stdout)[-4000:])


def installa(slugs, demo=False, riavvia=False, conferma=None):
    info = modules.scopri()
    attuali = modules.installati()
    richiesti = [s for s in slugs if s not in attuali] or _errore(GiaInstallato, slugs)
    piano = [s for s in modules.ordina(_chiusura(richiesti, info), info) if s not in attuali]
    for s in piano:                      # manifest valido e min_core: ManifestNonValido altrimenti
        if info[s].manifest is None: raise ManifestNonValido([info[s].errore])
    extra = [s for s in piano if s not in richiesti]
    if extra and conferma and not conferma(extra):
        return []
    backup.esegui("pre-installa-" + "-".join(piano))
    scrivi_stato(modules.ordina(attuali + piano, info))
    try:
        _applica("installa", piano, demo=demo)
    except ApplicaFallita as e:
        scrivi_stato(attuali)
        Modulo.objects.filter(slug__in=piano).update(stato=Modulo.ERRORE, ultimo_errore=str(e))
        raise
    if riavvia:
        reload.richiedi()
    return piano
```
`aggiorna(slugs|tutti)` e `disinstalla(slug, elimina_dati, riavvia)` seguono lo stesso schema (backup → `_applica` → stato). Per `disinstalla`: controllo dei dipendenti tra gli installati, `_applica("disinstalla", [slug], elimina_dati=...)`, **poi** `scrivi_stato` senza lo slug. `_chiusura` aggiunge ricorsivamente le dipendenze.

- [ ] **Step 4: `_modulo_applica`**

Comando nascosto (`help` lo dice: "uso interno di modulo"). Argomenti: `operazione` (`installa|aggiorna|disinstalla`), `slugs`, `--demo`, `--elimina-dati`. Per ogni slug nell'ordine dato:
- `installa`: `call_command("migrate", slug, interactive=False, verbosity=1)`; `carica_fixture(manifest, demo)`; `gruppi = crea_gruppi(manifest)`; `esegui_hook(manifest, "post_install", modulo)`; `aggiorna_riga(manifest, stato=INSTALLATO, versione_installata=manifest.version, installato_il=now, gruppi_creati=gruppi)`.
- `aggiorna`: `da = riga.versione_installata`; migrate; fixture `data`; gruppi; `esegui_hook(..., "post_upgrade", modulo, da)`; riga con `aggiornato_il`.
- `disinstalla`: `esegui_hook(..., "pre_uninstall", modulo)`; `Group.objects.filter(name__in=riga.gruppi_creati).delete()`; se `--elimina-dati`: `call_command("migrate", slug, "zero", interactive=False)`; riga → `DISPONIBILE`, `versione_installata=""`, `gruppi_creati=[]`.
- Alla fine, se `not settings.DEBUG`: `call_command("collectstatic", interactive=False, verbosity=0)`.
Qualsiasi eccezione → stack su stderr, exit 1. Tutto dentro `transaction.atomic()` **per modulo**, tranne `migrate`, che gestisce le proprie transazioni.

- [ ] **Step 5: sottocomandi di `modulo`**

`installa <slug>... [--demo] [--riavvia] [--si]`: la `conferma` stampa le dipendenze aggiuntive e chiede `[s/N]` salvo `--si`. `aggiorna <slug>...|--tutti [--riavvia]`, `disinstalla <slug> [--elimina-dati] [--riavvia] [--si]` (`--si` salta la conferma di `--elimina-dati`). Errori `ErroreInstallazione`/`ManifestNonValido`/`BackupFallito` → `CommandError`.

Run: `pytest core/tests -v` — Expected: passed.

- [ ] **Step 6: commit** — `feat(core): installazione, aggiornamento e disinstallazione dei moduli con backup, gruppi, hook e ricarica`

---

### Task 8: `ModelView` — base, registro, URL, lista, filtri, widget

**Files:**
- Create: `core/viste/__init__.py`, `base.py`, `registry.py`, `lista.py`, `filtri.py`, `widgets.py`
- Create: `core/templatetags/__init__.py`, `core/templatetags/vista.py`
- Create: `core/templates/core/vista/lista.html`, `_tabella.html`
- Create: `core/templates/core/base_app.html` (minimo: estende `theme/base.html`, blocco `app_content`; la barra dell'app arriva in Task 10)
- Modify: `core/views.py` (`AziendaView`), `core/urls.py` (monta `registry.urlpatterns("core")`)
- Test: `core/tests/test_modelview_lista.py`

- [ ] **Step 1: test (falliscono)**

Con `AziendaView` registrata in `core` (`list_display=["nome","partita_iva","citta","attiva"]`, `list_filter=["attiva","provincia"]`, `search_fields=["nome","partita_iva"]`, `ordering=["nome"]`, `per_page=5`, `col_citta` che restituisce `citta.upper()`), più aziende create nel test:
- `reverse("core:azienda_lista") == "/core/aziende/"` ... **attenzione**: lo slug della vista è `aziende` (`slug = "aziende"`), quindi `core:aziende_lista`; i nomi generati sono `<slug>_lista|_nuovo|_dettaglio|_modifica|_elimina|_azione|_bottone`;
- utente senza `core.view_azienda` → 403; con il permesso → 200 e le righe;
- `?q=acme` filtra con `icontains` su nome e partita_iva; `?f_attiva=0` filtra i falsi; `?f_provincia=CA`; `?o=-nome` inverte; `?o=campo_non_in_list_display` ignorato; `?p=2` pagina 2 con 5 per pagina e i link di paginazione conservano `q`, `f_*`, `o`;
- `?partial=1` oppure header `HX-Request: true` → risposta senza `<html`, con `id="tabella"`;
- `col_citta` → la cella mostra il maiuscolo; `attiva` reso come `ui-pill`; `None` come `—`;
- bottone "Nuovo" presente solo con `core.add_azienda`;
- `registry.per_modello(Azienda)` è l'istanza; `registry.viste_di("core")` la contiene; `registry.urlpatterns("core")` ha 7 pattern.

- [ ] **Step 2: base.py e registry.py**

```python
# core/viste/base.py
class ModelView:
    model = None
    slug = None
    verbose_name = None
    verbose_name_plural = None
    list_display = ("__str__",)
    list_filter = ()
    search_fields = ()
    ordering = ()
    per_page = 50
    form_layout = None            # [("Sezione", ["campo", ("affiancato1", "affiancato2")]), ...]
    form_class = None
    readonly_fields = ()
    company_field = None          # None = modello globale
    actions = ()                  # nomi di metodi (self, request, queryset) -> str|None
    buttons = ()                  # nomi di metodi (self, request, obj) -> HttpResponse|str|None
    api = False
    api_fields = None
    template_lista = "core/vista/lista.html"
    template_tabella = "core/vista/_tabella.html"
    template_form = "core/vista/form.html"
    template_dettaglio = "core/vista/dettaglio.html"
    template_conferma = "core/vista/_conferma.html"

    def __init__(self, modulo):
        self.modulo = modulo                                   # namespace URL = slug del modulo
        self.opts = self.model._meta
        self.slug = self.slug or self.opts.model_name
        self.verbose_name = self.verbose_name or self.opts.verbose_name
        self.verbose_name_plural = self.verbose_name_plural or self.opts.verbose_name_plural

    def nome_url(self, azione):
        return f"{self.modulo}:{self.slug}_{azione}"

    def url(self, azione, **kwargs):
        return reverse(self.nome_url(azione), kwargs=kwargs or None)

    def get_urls(self):
        from . import azioni, dettaglio, elimina, form, lista
        s = self.slug
        return [
            path(f"{s}/", lista.ListaView.as_view(vista=self), name=f"{s}_lista"),
            path(f"{s}/nuovo/", form.FormView.as_view(vista=self), name=f"{s}_nuovo"),
            path(f"{s}/<int:pk>/", dettaglio.DettaglioView.as_view(vista=self), name=f"{s}_dettaglio"),
            path(f"{s}/<int:pk>/modifica/", form.FormView.as_view(vista=self), name=f"{s}_modifica"),
            path(f"{s}/<int:pk>/elimina/", elimina.EliminaView.as_view(vista=self), name=f"{s}_elimina"),
            path(f"{s}/azione/<slug:nome>/", azioni.AzioneView.as_view(vista=self), name=f"{s}_azione"),
            path(f"{s}/<int:pk>/bottone/<slug:nome>/", azioni.BottoneView.as_view(vista=self), name=f"{s}_bottone"),
        ]

    def get_queryset(self, request):
        qs = self.model._default_manager.all()
        if self.company_field and getattr(request, "azienda", None) is not None:
            qs = qs.filter(**{self.company_field: request.azienda})
        return qs.order_by(*self.ordering) if self.ordering else qs

    def get_object(self, request, pk):
        return get_object_or_404(self.get_queryset(request), pk=pk)     # fuori azienda → 404

    def save_model(self, request, obj, form, change):
        if not change and self.company_field and getattr(obj, f"{self.company_field}_id", None) is None:
            setattr(obj, self.company_field, request.azienda)
        obj.save()
        form.save_m2m()

    def _perm(self, request, azione):
        return request.user.has_perm(f"{self.opts.app_label}.{azione}_{self.opts.model_name}")

    def has_view_permission(self, request, obj=None): return self._perm(request, "view")
    def has_add_permission(self, request): return self._perm(request, "add")
    def has_change_permission(self, request, obj=None): return self._perm(request, "change")
    def has_delete_permission(self, request, obj=None): return self._perm(request, "delete")

    def col_valore(self, request, obj, campo):
        metodo = getattr(self, f"col_{campo}", None)
        return metodo(obj) if metodo else widgets.rendi(self, obj, campo)
```
In Task 9 si aggiungono `get_form_class`, `layout`, `get_buttons`, `get_actions`. Per i template le viste generiche usano `vista.url("lista")` ecc. tramite un piccolo oggetto `urls` esposto nel contesto (`urls.lista`, `urls.nuovo`).

```python
# core/viste/registry.py
_viste: dict[str, list] = {}
_per_modello: dict = {}


def register(cls):
    modulo = cls.__module__.split(".")[0]
    vista = cls(modulo)
    _viste.setdefault(modulo, []).append(vista)
    _per_modello[vista.model] = vista
    return cls


def viste_di(modulo): return list(_viste.get(modulo, []))
def per_modello(model): return _per_modello.get(model)
def urlpatterns(modulo): return [p for v in viste_di(modulo) for p in v.get_urls()]


def autodiscover(moduli):
    """Importa <slug>.views dei moduli dati (come admin.autodiscover): è lì che @register viene eseguito."""
    for slug in moduli:
        if importlib.util.find_spec(f"{slug}.views"):
            importlib.import_module(f"{slug}.views")


def svuota():          # solo per i test
    _viste.clear(); _per_modello.clear()
```
`core/viste/__init__.py` esporta `ModelView` e `registry` (con `register = registry.register`).

- [ ] **Step 3: lista, filtri, widget, template**

`filtri.py`: `specifiche(vista, request)` → per ogni campo di `list_filter` un dict `{campo, label, tipo, opzioni, valore}` dal tipo di campo (`BooleanField` → sì/no; `choices`; FK → `queryset.all()` limitato a 200 e filtrato per azienda se il modello correlato ha `azienda`; `DateField` → `da`/`a`); `applica(vista, request, qs)` → `q`, `f_*`, `o` (solo campi in `list_display` che sono campi del modello); `querystring_senza(request, "p")` per la paginazione. `widgets.rendi(vista, obj, campo)`: `__str__`, bool → `ui-pill ui-pill-ok|neutral`, date → `d/m/Y`, datetime → `d/m/Y H:i`, FK → link al dettaglio se `registry.per_modello(related)` esiste e l'utente può vederlo, choices → `get_<campo>_display`, `None`/`""` → `—`; sempre `mark_safe` solo su HTML costruito con `format_html`.

`lista.py`: `ListaView(View)` con `vista` come attributo di classe passato da `as_view`; `login_required` via `LoginRequiredMixin`; 403 con `PermissionDenied` se `not has_view_permission`; contesto: `vista`, `urls`, `colonne` (`[{campo, label, ordinabile, direzione}]`), `righe` (`[(obj, [celle])]`), `filtri`, `page_obj`, `qs_base`, `puo_aggiungere`, `azioni` (vuoto fino al Task 9). Risposta parziale se `request.GET.get("partial")` o `request.headers.get("HX-Request")`.

`lista.html` (estende `core/base_app.html`): `ui-pagehead` con `verbose_name_plural` e bottone Nuovo; `ui-card` con `<form class="ui-filtri" method="get" hx-get="{{ urls.lista }}" hx-target="#tabella" hx-select="#tabella" hx-swap="outerHTML" hx-push-url="true" hx-trigger="submit, change, keyup changed delay:300ms from:[name=q]">` (campo `q`, un select per filtro, reset); `{% include vista.template_tabella %}`. `_tabella.html`: `<div id="tabella">` con `ui-table-wrap`, intestazioni ordinabili (link con `?o=`), righe (prima colonna = link al dettaglio), empty state, paginazione (`ui-pagination`, da aggiungere a `ui.css` se manca, con lo stile dei bottoni secondari).

`templatetags/vista.py`: `{% querystring_con p=2 %}` (ricostruisce la query conservando il resto), `{% cella vista obj campo %}`.

`core/views.py`: `AziendaView(ModelView)` con `@register`, attributi come nel test; `core/urls.py`: `*registry.urlpatterns("core")` **dopo** le path esplicite, e `app_name = "core"` già presente.

Run: `pytest core/tests/test_modelview_lista.py -v` — Expected: passed. Apri `/core/aziende/` nel browser e prova ricerca, filtro, ordinamento con HTMX (la URL cambia senza ricaricare la pagina).

- [ ] **Step 4: commit** — `feat(core): ModelView con registro, URL generati e vista lista con ricerca, filtri e paginazione HTMX`

---

### Task 9: `ModelView` — form, dettaglio, elimina, azioni, bottoni, sezioni di dettaglio

**Files:**
- Create: `core/viste/form.py`, `dettaglio.py`, `elimina.py`, `azioni.py`, `core/registry/hooks.py`
- Create: `core/templates/core/vista/form.html`, `_campo.html`, `dettaglio.html`, `_conferma.html`
- Modify: `core/viste/base.py`, `core/templatetags/vista.py`, `core/views.py` (`AziendaView`: `form_layout`, action `disattiva`, button `attiva`), `theme/static/theme/ui.css` (solo se mancano `.ui-form-row`, `.ui-modal`, `.ui-section`)
- Test: `core/tests/test_modelview_form.py`

- [ ] **Step 1: test (falliscono)**

- GET nuovo senza `add` → 403; con → 200, form con le sezioni del `form_layout` (titoli presenti, campi affiancati nella stessa `ui-form-row`); campo in `readonly_fields` assente dalla form e mostrato nel dettaglio;
- POST valido → 302 al dettaglio, oggetto creato, `messages` "creata"; POST non valido → 200 con l'errore sotto il campo (`ui-field-error`);
- modifica: GET precompilata; POST aggiorna;
- dettaglio: 200, mostra label e valore per ogni campo del layout, bottoni Modifica/Elimina solo con i permessi, `buttons` dichiarati come `<form method="post">`;
- elimina: GET con `HX-Request` → partial `_conferma.html` (contiene `hx-post`); GET normale → pagina intera di conferma; POST → 302 alla lista, oggetto rimosso, messaggio; senza `delete` → 403;
- azione: POST `core:aziende_azione nome=disattiva` con `pk=[...]` → le righe cambiano, messaggio, redirect alla lista; nome non in `actions` → 404; la lista mostra le checkbox e il select delle azioni solo se `actions` non è vuoto;
- bottone: POST `core:aziende_bottone pk nome=attiva` → chiama il metodo; `str` restituita → messaggio e redirect al dettaglio; `HttpResponse` restituita → usata così com'è;
- sezione: `hooks.sezione_dettaglio("core.Azienda", "core/tests/_sezione_prova.html", order=10)` (template creato nel test con `tmp` di `settings.TEMPLATES[0]["DIRS"]`, o un template dentro `core/tests/templates/`) → il dettaglio contiene il suo HTML con `obj` nel contesto; due sezioni rispettano `order`; sezione con `permission` non posseduta non compare; `hooks.svuota()` in una fixture `autouse`.

- [ ] **Step 2: implementazione**

`base.py` aggiunge:
```python
    def layout(self):
        """form_layout normalizzato: [(titolo, [[campo, ...], ...])], ogni riga una lista di campi."""
        if self.form_layout is None:
            campi = [f.name for f in self.opts.get_fields()
                     if getattr(f, "editable", False) and not f.auto_created and f.name not in self.readonly_fields]
            return [("", [[c] for c in campi])]
        return [(titolo, [list(r) if isinstance(r, (tuple, list)) else [r] for r in righe]) for titolo, righe in self.form_layout]

    def campi_form(self):
        return [c for _, righe in self.layout() for riga in righe for c in riga if c not in self.readonly_fields]

    def get_form_class(self):
        return self.form_class or modelform_factory(self.model, fields=self.campi_form())
```
`form.py`: `FormView` per `nuovo` e `modifica` (distingue da `kwargs.get("pk")`), permessi `add`/`change`, `save_model`, messaggi "«{obj}» creata/aggiornata" (usa `verbose_name`), redirect al dettaglio. `_campo.html` via `{% campo form.nome %}`: label, widget con classe `ui-input|ui-select|ui-textarea|ui-checkbox` scelta dal tipo di widget (filtro `con_classe`), errori, `help_text`. `dettaglio.py`: layout in sola lettura (`col_valore` per i valori), `buttons`, sezioni da `hooks.sezioni_per(model, request)`. `elimina.py`, `azioni.py` come nei test. `hooks.py`:
```python
_sezioni = defaultdict(list)   # "app.Model" -> [dict(template, order, permission)]

def sezione_dettaglio(model, template, order=100, permission=None): ...
def sezioni_per(model, request): ...   # ordinate, filtrate per permesso (superuser vede tutto)
def svuota(): ...
```
`AziendaView`: `form_layout=[("Anagrafica", ["nome", ("partita_iva", "codice_fiscale"), ("indirizzo", "cap"), ("citta", "provincia")]), ("Contatti", [("email", "telefono"), "logo", "attiva"])]`, `actions=["disattiva"]`, `buttons=["attiva"]`.

Run: `pytest core/tests -v` — Expected: passed. Prova nel browser creazione, modifica, eliminazione con modale, azione di massa.

- [ ] **Step 3: commit** — `feat(core): ModelView: form a sezioni, dettaglio con sezioni registrabili, eliminazione, azioni e bottoni`

---

### Task 10: Navigazione — barra dell'app, context processor, montaggio dei moduli, launcher, stile

**Files:**
- Create: `core/registry/urls.py`, `core/templates/core/partials/_menu_app.html`, `core/templates/core/launcher.html`
- Modify: `core/registry/modules.py` (`app_visibili`, `app_corrente`), `core/context_processors.py` (nuovo file), `core/templates/core/base_app.html`, `config/settings.py` (`context_processors`), `config/urls.py`, `core/views.py` (`home`), `core/templates/core/home.html` → rimosso, `core/templates/core/stile.html`, `core/apps.py` (`ready`: `registry.autodiscover(settings.ADDONS_ATTIVI)`)
- Test: `core/tests/test_nav.py`, `core/tests/test_launcher.py`

- [ ] **Step 1: test (falliscono)**

Con `addons_tmp` non si possono montare URL di moduli finti (l'urlconf è fissa per processo): i test usano `monkeypatch` su `modules.manifests_attivi` per far credere che esistano app `alfa` (`application=True`, menu con `url_name="core:aziende_lista"` e `permission="core.view_azienda"`) e `beta` (`application=False`):
- `theme.nav` nel contesto della home contiene `alfa` solo per chi ha `core.view_azienda` (il superuser sempre), mai `beta`;
- `app_corrente(request)` per una richiesta a `/core/aziende/` con namespace `core` → `None` (core non è un'app); con un `resolver_match` finto con namespace `alfa` → `alfa`, e `menu_app` sono le sue voci permesse;
- il launcher (`/`) mostra una card per app visibile con nome, summary, link; empty state con link a `/moduli/` per il superuser e senza link per gli altri;
- `patterns_moduli()` con `settings.ADDONS_ATTIVI=[]` → `[]`; con `todo` (Task 13) → un `URLResolver` con namespace `todo` (questo caso si verifica in Task 13).

- [ ] **Step 2: implementazione**

`core/registry/urls.py`:
```python
def patterns_moduli():
    registry.autodiscover(settings.ADDONS_ATTIVI)
    patterns = []
    for slug in settings.ADDONS_ATTIVI:
        propri = importlib.import_module(f"{slug}.urls").urlpatterns if importlib.util.find_spec(f"{slug}.urls") else []
        patterns.append(path(f"{slug}/", include((registry.urlpatterns(slug) + list(propri), slug))))
    return patterns
```
`config/urls.py`: `path("api/v1/", api.urls)` (Task 12), `include("core.urls")`, poi `*patterns_moduli()`.

`modules.app_visibili(user)`: per ogni manifest attivo con `application=True`, le voci di menu che l'utente può vedere (superuser tutto; `permission` assente = tutti; altrimenti `has_perm`); l'app è visibile se ha almeno una voce; restituisce `[{"slug","label","summary","icon","url_name","menu"}]`, con `url_name` = prima voce permessa. `app_corrente(request)`: `request.resolver_match.namespace` se è in `ADDONS_ATTIVI`.

`core/context_processors.py`:
```python
from theme.context_processors import theme as _theme   # core importa theme, mai il contrario


def piattaforma(request):
    base = _theme(request)["theme"]
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"theme": base}
    apps = modules.app_visibili(request.user)
    corrente = modules.app_corrente(request, apps)
    return {
        "theme": {**base, "nav": [{"label": a["label"], "url_name": a["url_name"]} for a in apps]},
        "apps": apps, "app_corrente": corrente, "menu_app": corrente["menu"] if corrente else [],
        "aziende": azienda.consentite(request.user), "azienda": getattr(request, "azienda", None),
    }
```
Messo in `context_processors` **dopo** `theme.context_processors.theme`. `base_app.html`: dentro `{% block content %}`, `{% include "core/partials/_menu_app.html" %}` se `app_corrente or aziende|length > 1`, poi `{% block app_content %}`. `_menu_app.html`: `<nav class="ui-appbar">` con nome app, voci (`is-active` sul `view_name` corrente), `settings_url` se presente, e `_aziende.html` a destra. Aggiungi `.ui-appbar` a `ui.css` nello stile dell'header (altezza 44px, bordo inferiore, link con stato attivo).

`launcher.html`: `ui-pagehead` "Le tue app" e una griglia `ui-apps` di card (icona: se `icon` contiene `/` → `<img src="{% static icon %}">`, altrimenti `<svg><use href="#icon-{{ icon }}"/></svg>`), nome, summary. `home` in `core/views.py` la rende. `stile.html`: aggiungi gli esempi di `ui-appbar`, `ui-filtri`, `ui-form-row`, modale di conferma, `ui-apps`.

Run: `pytest -v` — Expected: passed.

- [ ] **Step 3: commit** — `feat(core): navigazione dinamica dai manifest, barra dell'app, launcher e montaggio degli URL dei moduli`

---

### Task 11: Pagina Moduli

**Files:**
- Create: `core/templates/core/moduli.html`, `core/templates/core/partials/_moduli_stato.html`
- Modify: `core/views.py`, `core/urls.py`, `core/admin.py` (`ModuloAdmin` sola lettura con link a `/moduli/`)
- Test: `core/tests/test_moduli_pagina.py`

- [ ] **Step 1: test (falliscono)**

- `/moduli/` → 302 per anonimo, 403 per staff non superuser, 200 per superuser; chiama `sincronizza()` e mostra una card per modulo con nome, versione, stato e i bottoni giusti per stato (`disponibile` → Installa con checkbox demo; `installato` → Disinstalla con checkbox "elimina dati"; `da_aggiornare` → Aggiorna e Disinstalla; `mancante`/`errore` → solo Disinstalla, e l'errore in un `ui-alert`);
- `POST /moduli/azione/` con `op=installa&slug=alfa` → `subprocess.Popen` chiamato (monkeypatch) con `[sys.executable, ".../manage.py", "modulo", "installa", "alfa", "--si", "--riavvia"]`, `start_new_session=True`, stdout su un file in `logs/`; risposta 200 con il partial `_moduli_stato.html` che contiene `hx-get` verso `/moduli/stato/?log=<nome>`; `op=installa` con `demo=1` aggiunge `--demo`; `op=disinstalla` con `elimina_dati=1` aggiunge `--elimina-dati`; `slug` non tra quelli scoperti → 400; `op` sconosciuta → 400;
- `/moduli/stato/?log=<nome>` → coda del log (ultime 60 righe), `in_corso` finché il processo non ha scritto la riga finale `== FINE <esito> ==` (la scrive il comando `modulo`), e `completato`/`fallito` dopo; nome di log con `/` o `..` → 400;
- `Modulo` nell'admin: `has_add_permission` e `has_change_permission` falsi, `list_display` con stato.

- [ ] **Step 2: implementazione**

Viste `moduli` (GET), `moduli_azione` (POST), `moduli_stato` (GET), decorate con `user_passes_test(lambda u: u.is_superuser)`. Il log: `logs/moduli-<slug>-<timestamp>.log` aperto in scrittura e passato a `Popen(stdout=f, stderr=subprocess.STDOUT, cwd=BASE_DIR, start_new_session=True)`; il comando `modulo` stampa `== FINE ok ==` o `== FINE errore ==` come ultima riga (aggiungilo al comando, anche per la CLI). `_moduli_stato.html`: `<div id="stato" hx-get="..." hx-trigger="every 2s" hx-swap="outerHTML">` con `<pre class="ui-log">` e, a fine lavoro, un link "Ricarica la pagina". `moduli.html` estende `base_app.html`. Link "Moduli" nel dropdown del profilo del theme: **no** (theme non conosce core); si aggiunge invece una voce "Moduli" nel launcher per il superuser e un link dall'admin (`ModuloAdmin.changelist` con un `ui-alert` in `change_list_template`).

Run: `pytest core/tests/test_moduli_pagina.py -v` — Expected: passed.

- [ ] **Step 3: commit** — `feat(core): pagina Moduli con installazione, aggiornamento e disinstallazione dall'interfaccia`

---

### Task 12: API

**Files:**
- Create: `core/api/__init__.py`, `core/api/auth.py`, `core/api/fissi.py`, `core/api/modelli.py`
- Modify: `config/urls.py`, `core/views.py` (`profilo`: token), `core/forms.py`, `core/templates/core/profilo.html`, `core/urls.py` (`core:token_nuovo`, `core:token_revoca`), `core/admin.py` (`TokenApi`)
- Test: `core/tests/test_api.py`, `core/tests/test_profilo_token.py`

- [ ] **Step 1: test (falliscono)**

`test_api.py` (usa `AziendaView` con `api=True`, `api_fields=["nome","partita_iva","citta","attiva"]`):
- senza credenziali → 401; con sessione (client loggato) → 200; con `Authorization: Bearer <chiaro>` → 200; token revocato → 401;
- `GET /api/v1/core/aziende/` → `{"count","page","per_page","results":[{...,"id"}]}`, rispetta `q`, `f_attiva`, `o`, `p`, `per_page` (massimo 200); utente senza `core.view_azienda` → 403;
- `POST` valido → 201 con l'oggetto; non valido → 422 `{"errori": {"nome": ["..."]}}`; senza `add` → 403;
- `GET /<pk>/` → 200; pk di un'altra azienda per un modello con `company_field` → 404 (verificato in Task 13 con `todo`);
- `PATCH /<pk>/` parziale → 200 e aggiorna solo i campi dati; `DELETE` → 204;
- `X-Azienda: <pk non consentita>` → 403; consentita → `request.azienda` corrispondente (verificato con `todo` in Task 13);
- `GET /api/v1/me/` → utente, aziende, app visibili; `GET /api/v1/moduli/` → 403 per non superuser, elenco per superuser;
- `/api/v1/docs` → 302 per anonimo, 200 per loggato;
- una `ModelView` con `api=False` (una seconda vista di prova registrata nel test con `registry.register` su `ProfiloUtente`) non ha endpoint → 404. Attenzione: i router Ninja si costruiscono all'import di `core.api`, quindi questo test deve usare una vista registrata **prima** (in `core/views.py`: `ProfiloUtenteView` con `api=False`, non montata nel menu).

`test_profilo_token.py`: `/profilo/` mostra i token dell'utente; `POST core:token_nuovo nome=cli` → crea e mostra il chiaro **una sola volta** (nella pagina successiva non c'è); `POST core:token_revoca pk` → `attivo=False`; revocare un token altrui → 404.

- [ ] **Step 2: implementazione**

```python
# core/api/auth.py
class TokenAuth(HttpBearer):
    def authenticate(self, request, token):
        t = TokenApi.verifica(token)
        if t:
            request.user = t.utente
            return t.utente


def azienda_per(request):
    """X-Azienda se consentita (403 altrimenti), altrimenti request.azienda."""
```

```python
# core/api/__init__.py
api = NinjaAPI(title="adabox-hub", version=__version__, auth=[django_auth, TokenAuth()], csrf=True,
               docs_decorator=login_required, urls_namespace="api")
from . import fissi, modelli  # noqa: E402,F401  (registrano i router)
```

`modelli.py`: all'import, `registry.autodiscover(settings.ADDONS_ATTIVI)`; poi per ogni modulo in `["core", *ADDONS_ATTIVI]` e ogni vista con `api=True`, `_router_per(vista)` → `Router(tags=[vista.modulo])` con cinque operazioni che riusano `vista.get_queryset`, `filtri.applica`, `has_*_permission`, `get_form_class`, `save_model`; output serializzato da `serializza(vista, obj)` (dict: `id`, campi di `api_fields`, FK come id più `<fk>_display`, date ISO) e dichiarato con `create_schema(vista.model, name=f"{vista.modulo}_{vista.slug}", fields=[...], custom_fields=[(f"{fk}_display", str, "")...])`; input `dati: dict = Body(...)`, validato dalla `ModelForm` della vista (`PATCH` unisce `model_to_dict(obj)` con i dati); `api.add_router(f"/{vista.modulo}/{vista.slug}", router)`. `fissi.py`: `/me/` e `/moduli/`.

Profilo: `TokenApiForm(nome)`, viste `token_nuovo` e `token_revoca`; il chiaro passa nella sessione per la pagina successiva e viene cancellato dopo la lettura.

Run: `pytest -v` — Expected: passed. Apri `/api/v1/docs`.

- [ ] **Step 3: commit** — `feat(core): API JSON generica con Django Ninja, token per utente e endpoint me/moduli`

---

### Task 13: App di riferimento `todo` e test di installazione vergine

**Files:**
- Create: `addons/todo/__manifest__.py`, `__init__.py`, `apps.py`, `models.py`, `views.py`, `hooks.py`, `migrations/0001_initial.py`, `data/tag.json`, `data/demo.json`, `static/todo/icon.svg`, `tests/__init__.py`, `tests/test_todo.py`, `tests/test_installazione.py`
- Test: come sopra più `core/tests/test_nav.py` (caso `patterns_moduli` con `todo`)

- [ ] **Step 1: manifest, modelli, viste**

`addons/todo/__manifest__.py`: come nella spec (sezione "Manifest"), con `"icon": "todo/icon.svg"`, `"hooks": "todo.hooks"`, `"data": ["data/tag.json"]`, `"demo": ["data/demo.json"]`.

`models.py`:
```python
from django.conf import settings
from django.db import models

from core.mixins import AziendaMixin


class Tag(models.Model):
    nome = models.CharField("nome", max_length=40, unique=True)
    colore = models.CharField("colore", max_length=7, default="#1e3a8a")

    class Meta:
        verbose_name = "tag"
        verbose_name_plural = "tag"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Attivita(AziendaMixin):
    APERTA, IN_CORSO, FATTA, ANNULLATA = "aperta", "in_corso", "fatta", "annullata"
    STATI = [(APERTA, "Aperta"), (IN_CORSO, "In corso"), (FATTA, "Fatta"), (ANNULLATA, "Annullata")]
    titolo = models.CharField("titolo", max_length=200)
    descrizione = models.TextField("descrizione", blank=True)
    scadenza = models.DateField("scadenza", null=True, blank=True)
    assegnatario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="attivita_assegnate", verbose_name="assegnatario")
    stato = models.CharField("stato", max_length=12, choices=STATI, default=APERTA)
    tag = models.ManyToManyField(Tag, blank=True, verbose_name="tag")
    creato = models.DateTimeField("creato il", auto_now_add=True)
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", editable=False)

    class Meta:
        verbose_name = "attività"
        verbose_name_plural = "attività"
        ordering = ["-scadenza", "-creato"]

    def __str__(self):
        return self.titolo
```
`views.py`: `AttivitaView` (come nella spec, `company_field="azienda"`, `readonly_fields=["creato"]`, `actions=["archivia"]`, `buttons=["segna_fatta"]`, `api=True`, `save_model` che imposta `creato_da` alla creazione) e `TagView` (`api=True`). `hooks.py`: `post_install(modulo)` aggiunge il gruppo "To-Do / Utente" a tutti gli utenti attivi. `data/tag.json`: tre tag (pk 1-3). `data/demo.json`: dieci attività con `azienda: 1` e stati vari. `icon.svg`: un quadrato con spunta, 48x48, colore `currentColor`. Migrazione: `ADDONS_FORCE=todo python manage.py makemigrations todo` (la variabile serve perché `todo` non è nel file di stato).

- [ ] **Step 2: test dell'app**

`tests/test_todo.py` (gira perché `pytest.ini` forza `todo`): modelli; lista/nuovo/dettaglio con un utente del gruppo "To-Do / Utente" (gruppo creato nel test con `crea_gruppi(manifest.leggi(...))`); attività di un'altra `Azienda` → 404 nel dettaglio e assente dalla lista; API `GET /api/v1/todo/attivita/` con `X-Azienda` dell'altra azienda (consentita) mostra solo le sue; `archivia` e `segna_fatta`; `creato_da` impostato; launcher e `theme.nav` mostrano "To-Do" per l'utente del gruppo e non per uno senza permessi; `patterns_moduli()` contiene il namespace `todo` e `reverse("todo:attivita_lista") == "/todo/attivita/"`.

`tests/test_installazione.py` (end-to-end nel sottoprocesso, marcato `@pytest.mark.slow`):
```python
def test_installazione_vergine(tmp_path):
    addons = tmp_path / "addons"; addons.mkdir()
    shutil.copytree(BASE_DIR / "addons" / "todo", addons / "todo")
    env = {**os.environ, "ADDONS_DIR": str(addons), "DATABASE_URL": f"sqlite:///{tmp_path/'db.sqlite3'}",
           "BACKUP_DIR": str(tmp_path / "backup"), "RELOAD_STRATEGY": "none", "DEBUG": "True"}
    env.pop("ADDONS_FORCE", None)
    run = lambda *args: subprocess.run([sys.executable, "manage.py", *args], cwd=BASE_DIR, env=env,
                                       capture_output=True, text=True, check=True)
    run("migrate", "--noinput")
    run("modulo", "installa", "todo", "--demo", "--si")
    assert "todo" in json.loads((addons / "installed.json").read_text())["installed"]
    assert "installato" in run("modulo", "lista").stdout
    conta = run("shell", "-c", "from todo.models import Attivita; print(Attivita.objects.count())").stdout
    assert conta.strip() == "10"
    assert list((tmp_path / "backup").glob("*-pre-installa-todo.sqlite3"))
    run("modulo", "disinstalla", "todo", "--elimina-dati", "--si")
    tabelle = run("shell", "-c", "from django.db import connection; print(connection.introspection.table_names())").stdout
    assert "todo_attivita" not in tabelle
```
Registra il marker `slow` in `pytest.ini` (`markers = slow: test lenti end-to-end`).

- [ ] **Step 3: installazione in sviluppo**

```bash
python manage.py migrate
python manage.py modulo installa todo --demo --si
python manage.py modulo lista
```
Riavvia `runserver`, apri `/`: la card To-Do; `/todo/attivita/`: le dieci attività. `/moduli/`: To-Do installato.

Run: `pytest -v` — Expected: tutto verde, compreso il test lento.

- [ ] **Step 4: commit** — `feat(todo): app di riferimento To-Do con attività, tag, gruppi, dati demo e test di installazione vergine`

---

### Task 14: Docker, entrypoint, README, verifica

**Files:**
- Create: `deploy/entrypoint.sh`
- Modify: `Dockerfile`, `docker-compose.yml`, `.env.example`, `README.md`, `.dockerignore`
- Test: `config/tests/test_deploy.py` invariato deve restare verde

- [ ] **Step 1: deploy**

`deploy/entrypoint.sh`:
```sh
#!/bin/sh
set -e
python manage.py collectstatic --noinput
python manage.py migrate --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 60 --pid /tmp/gunicorn.pid
```
`Dockerfile`: `apt-get install -y --no-install-recommends postgresql-client`, `COPY deploy/entrypoint.sh`, `chmod +x`, `CMD ["deploy/entrypoint.sh"]`. `docker-compose.yml`: volumi `./addons:/app/addons`, `./backup:/app/backup`, `./media:/app/media`; `RELOAD_STRATEGY=gunicorn` nell'`environment` del servizio `web`. `.dockerignore`: `backup/`, `media/`, `addons/installed.json` **no** (lo stato deve entrare nel volume, non nell'immagine: con il volume montato il file dell'host vince).

- [ ] **Step 2: README**

Riscrivi `README.md` per adabox-hub: cos'è, struttura, avvio in sviluppo (venv, `.env`, `migrate`, `createsuperuser`, `modulo installa todo --demo`, `runserver`), come si scrive un'app (manifest, `ModelView`, gruppi, fixture, hook, test), comandi `modulo`, pagina `/moduli/`, backup e ripristino (sqlite: copia; Postgres: `pg_restore`), produzione (gunicorn con pidfile, volumi, `RELOAD_STRATEGY`), sicurezza (sezione ereditata dallo starter), test (`pytest`, `pytest -m "not slow"`).

- [ ] **Step 3: verifica finale**

```bash
pytest -v
DEBUG=False SECRET_KEY=x ALLOWED_HOSTS=localhost python manage.py check --deploy
docker compose build && docker compose up -d && sleep 5 && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8096/accounts/login/
docker compose exec web python manage.py modulo installa todo --demo --si --riavvia
sleep 3 && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8096/todo/attivita/   # 302 al login
docker compose down
```
Nel browser, con `runserver`: login, launcher, To-Do (lista, filtri, nuovo, dettaglio, elimina, azione), `/moduli/` (disinstalla e reinstalla To-Do dall'interfaccia con riavvio automatico), `/api/v1/docs`, `/profilo/` con un token, `/stile/`.

- [ ] **Step 4: commit** — `feat: deploy con entrypoint e pidfile, volumi per addons e backup, README della piattaforma`

---

## Self-review (fatta in scrittura)

- **Copertura spec:** manifest (T2), stato e bootstrap (T1), registro e stati (T5), backup (T6), installazione/aggiornamento/disinstallazione/gruppi/hook/ricarica (T7), `ModelView` lista (T8) e form/dettaglio/elimina/azioni/bottoni/sezioni (T9), navigazione, launcher, montaggio moduli (T10), pagina Moduli (T11), API e token (T12), `todo` e installazione vergine (T13), Docker e README (T14). Modelli del kernel e azienda corrente (T3, T4).
- **Coerenza nomi:** `core.registry.{bootstrap,manifest,modules,install,groups,reload,hooks,urls}`; `core.viste.{ModelView,registry}`; nomi URL `<slug>_lista|_nuovo|_dettaglio|_modifica|_elimina|_azione|_bottone` (T8, T9, T12, T13); `core:aziende_*` per `AziendaView` con `slug="aziende"`; settings `ADDONS_DIR`, `ADDONS_ATTIVI`, `BACKUP_DIR`, `BACKUP_CONSERVA`, `RELOAD_STRATEGY`, `GUNICORN_PIDFILE` (T1, T6, T7, T14); fixture `addons_tmp.crea` (T1, usata da T2, T5, T7); riga finale `== FINE ok|errore ==` del comando (T11).
- **Rischi noti:** (1) i test che hanno bisogno di un modulo montato negli URL usano `todo` forzato da `ADDONS_FORCE` in `pytest.ini`, non moduli finti: l'urlconf è fissa per processo; (2) il sottoprocesso di `_applica` eredita l'ambiente, quindi i test e la pagina Moduli devono passare `ADDONS_DIR`/`DATABASE_URL` coerenti; il test end-to-end toglie `ADDONS_FORCE`; (3) la ricarica con `runserver` tocca `config/settings.py`: funziona con lo StatReloader di default, non con un reloader esterno; (4) `create_schema` di Ninja con `custom_fields` va verificato sulla versione installata: se non supporta i resolver, si dichiara la risposta come `dict` e si perde solo la tipizzazione nello Swagger, non il comportamento.
