# django-template — piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Uno starter Django da clonare, con l'admin e il frontend nello stile grafico di SIEE-ENAS e la sicurezza di base già configurata.

**Architecture:** Progetto Django 5.2 con tre pacchetti: `config/` (settings via env), `theme/` (tutta la grafica, autosufficiente: template admin, shell frontend, CSS a token, JS minimo, favicon dinamica) e `core/` (app di esempio con un modello, home, catalogo stile, profilo). Il brand sta in `settings.THEME`, i colori in `theme/static/theme/tokens.css`.

**Tech Stack:** Python 3.12, Django 5.2, django-environ, django-axes 8, psycopg[binary], gunicorn; pytest + pytest-django. Nessuna dipendenza frontend.

**Spec:** `docs/superpowers/specs/2026-10-09-django-template-design.md`

**Regole per chi esegue:**
- Repo di lavoro: `/home/adauser/part_dati/django-template`. Tutti i comandi partono da lì.
- Il repo `/home/adauser/part_dati/SIEE_Enas` è **sola lettura**: si legge con `sed -n`/`cat`, non si crea né modifica nulla dentro. Variabile usata nel piano: `SRC=/home/adauser/part_dati/SIEE_Enas/prototype`.
- Virtualenv: `.venv` nel repo (`python3 -m venv .venv && . .venv/bin/activate`). Ogni comando `python`/`pytest` presuppone il venv attivo.
- Commit in italiano, prefisso tipo `feat(theme): …`, chiudere con `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Due scostamenti dalla spec, decisi qui: (1) la favicon è una view che genera un SVG con la sigla di `THEME["mark"]` invece di file statici, così cambia col brand; (2) il template della CSRF failure si chiama `403_csrf.html` (nome che Django cerca da solo), non `csrf_failure.html`.

---

## Mappa dei file

| File | Responsabilità |
|---|---|
| `requirements.txt`, `requirements-dev.txt` | dipendenze bloccate |
| `.env.example`, `.gitignore`, `pytest.ini`, `manage.py` | impianto |
| `config/settings.py` | settings unico via env; sicurezza; logging |
| `config/urls.py` | admin, auth, theme (favicon), core |
| `config/wsgi.py` | entrypoint gunicorn |
| `config/tests/test_settings.py` | flag di produzione con DEBUG=False |
| `theme/apps.py` | AppConfig |
| `theme/context_processors.py` | `theme` nei template (default + settings.THEME) |
| `theme/views.py`, `theme/urls.py` | favicon SVG dinamica |
| `theme/static/theme/tokens.css` | design token `--ui-*` |
| `theme/static/theme/admin.css` | override admin Django (port di `siee-admin.css`) |
| `theme/static/theme/ui.css` | componenti frontend (port di `siee.css`) |
| `theme/static/theme/ui.js` | dropdown, menu mobile, toggle password, reveal tabelle, toast |
| `theme/templates/admin/base_site.html` | branding admin |
| `theme/templates/theme/base.html` + `partials/` | shell frontend |
| `theme/templates/registration/*.html`, `lockout.html`, `4xx/5xx.html` | pagine auth ed errori |
| `theme/tests/test_portabilita.py`, `test_pagine.py` | nessun import da core/config; pagine theme |
| `core/models.py`, `admin.py`, `views.py`, `forms.py`, `urls.py` | app di esempio |
| `core/templates/core/{home,stile,profilo}.html` | pagine esempio |
| `core/tests/test_pagine.py`, `test_axes.py` | pagine core, admin, lockout |
| `README.md` | procedura nuovo cliente |

---

### Task 1: Impianto del progetto (settings, urls, app vuote)

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `.env.example`, `.gitignore`, `pytest.ini`, `manage.py`
- Create: `config/__init__.py`, `config/settings.py`, `config/urls.py`, `config/wsgi.py`
- Create: `theme/__init__.py`, `theme/apps.py`, `theme/context_processors.py`
- Create: `core/__init__.py`, `core/apps.py`, `core/urls.py`, `core/views.py`
- Test: `theme/tests/__init__.py`, `theme/tests/test_context.py`

- [ ] **Step 1: Dipendenze e venv**

`requirements.txt`:
```
Django==5.2.17
django-environ==0.14.0
django-axes==8.3.1
psycopg[binary]==3.3.6
gunicorn==26.2.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==9.0.2
pytest-django==4.11.1
```

Run: `cd /home/adauser/part_dati/django-template && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt`
Expected: installazione senza errori. Se una versione non esiste su PyPI, usare l'ultima disponibile della stessa major e annotarlo nel commit.

- [ ] **Step 2: File di impianto**

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
.env
db.sqlite3
staticfiles/
logs/
.pytest_cache/
```

`.env.example`:
```
# Chiave segreta: generala con  python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
SECRET_KEY=cambiami
# True solo in sviluppo. Con False si attivano cookie secure, proxy header e logging su file.
DEBUG=True
# Host ammessi, separati da virgola (es. app.cliente.it,10.0.0.5)
ALLOWED_HOSTS=localhost,127.0.0.1
# Origini fidate per CSRF quando si sta dietro a un proxy HTTPS (es. https://app.cliente.it)
CSRF_TRUSTED_ORIGINS=
# Database: sqlite di default; Postgres es. postgres://utente:password@localhost:5432/nomedb
DATABASE_URL=sqlite:///db.sqlite3
# Destinatari delle mail di errore 500 (Nome:email, separati da virgola)
ADMINS=
# Tentativi di login falliti prima del blocco, e durata del blocco in minuti
AXES_FAILURE_LIMIT=5
AXES_COOLOFF_MINUTES=15
# Solo produzione: 1 per forzare https (dietro proxy che passa X-Forwarded-Proto)
SECURE_SSL_REDIRECT=False
# HSTS: lasciare 0 finché il 443 non è verificato; poi es. 31536000
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
```

`pytest.ini`:
```
[pytest]
DJANGO_SETTINGS_MODULE = config.settings
python_files = test_*.py
```

`manage.py`:
```python
#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

Run: `chmod +x manage.py`

- [ ] **Step 3: settings.py**

`config/__init__.py`: vuoto.

`config/settings.py`:
```python
"""
Settings unico: sviluppo e produzione differiscono solo per DEBUG e per le
variabili in .env (vedi .env.example).
"""
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="solo-sviluppo-cambiami")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Brand: letto dal context processor theme.context_processors.theme
THEME = {
    "brand": "Progetto",
    "mark": "PR",
    "company": "ICHNOBYTE S.R.L.",
    "company_url": "https://ichnobyte.it/",
    "version": "0.1.0",
    "nav": [
        {"label": "Home", "url_name": "core:home"},
        {"label": "Stile", "url_name": "core:stile"},
    ],
}

INSTALLED_APPS = [
    "theme",  # prima di admin: sovrascrive admin/base_site.html
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "axes",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "theme.context_processors.theme",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "it"
TIME_ZONE = "Europe/Rome"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sicurezza sempre attiva -------------------------------------------
SESSION_COOKIE_AGE = 60 * 30
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

# django-axes: blocco per coppia username+ip, reset al login riuscito
AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = timedelta(minutes=env.int("AXES_COOLOFF_MINUTES", default=15))
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "lockout.html"

# --- Solo produzione (DEBUG=False) ---------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
    CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
    SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
    AXES_IPWARE_PROXY_COUNT = 1
    AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]

# --- Mail di errore e logging -------------------------------------------
ADMINS = [tuple(p.split(":", 1)) for p in env.list("ADMINS", default=[]) if ":" in p]
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

LOG_DIR = BASE_DIR / "logs"
_file_handlers = {}
_file_handler_names = []
if not DEBUG:
    LOG_DIR.mkdir(exist_ok=True)
    _file_handlers = {
        "file_app": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "app.log",
            "maxBytes": 5 * 1024 * 1024, "backupCount": 5,
            "level": "INFO", "formatter": "std",
        },
        "file_error": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "error.log",
            "maxBytes": 5 * 1024 * 1024, "backupCount": 5,
            "level": "ERROR", "formatter": "std",
        },
    }
    _file_handler_names = ["file_app", "file_error"]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
        "mail_admins": {"class": "django.utils.log.AdminEmailHandler", "level": "ERROR"},
        **_file_handlers,
    },
    "root": {"handlers": ["console", *_file_handler_names], "level": "INFO"},
    "loggers": {
        "django.request": {
            "handlers": ["console", "mail_admins", *_file_handler_names],
            "level": "ERROR", "propagate": False,
        },
    },
}
```

- [ ] **Step 4: urls.py e wsgi.py**

`config/urls.py`:
```python
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password_change/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("accounts/password_change/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("", include("theme.urls")),
    path("", include("core.urls")),
]
```

`config/wsgi.py`:
```python
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()
```

- [ ] **Step 5: test del context processor (fallisce)**

`theme/__init__.py`, `theme/tests/__init__.py`: vuoti.

`theme/tests/test_context.py`:
```python
from django.test import RequestFactory, override_settings

from theme.context_processors import theme


def test_default_senza_settings():
    with override_settings(THEME={}):
        ctx = theme(RequestFactory().get("/"))
    assert ctx["theme"]["brand"] == "Progetto"
    assert ctx["theme"]["mark"] == "PR"
    assert ctx["theme"]["nav"] == []


def test_settings_sovrascrivono_i_default():
    with override_settings(THEME={"brand": "Acme", "mark": "AC"}):
        ctx = theme(RequestFactory().get("/"))
    assert ctx["theme"]["brand"] == "Acme"
    assert ctx["theme"]["company"] == ""
```

Run: `pytest theme/tests/test_context.py -v`
Expected: FAIL, `ModuleNotFoundError: theme.context_processors` (o errore di import di `core`).

- [ ] **Step 6: app theme e core minime**

`theme/apps.py`:
```python
from django.apps import AppConfig


class ThemeConfig(AppConfig):
    name = "theme"
    verbose_name = "Tema grafico"
```

`theme/context_processors.py`:
```python
from django.conf import settings

DEFAULTS = {
    "brand": "Progetto",
    "mark": "PR",
    "company": "",
    "company_url": "",
    "version": "",
    "nav": [],
}


def theme(request):
    """Espone `theme` ai template: default + settings.THEME."""
    return {"theme": {**DEFAULTS, **getattr(settings, "THEME", {})}}
```

`theme/urls.py` (la favicon arriva nel Task 2; per ora vuoto):
```python
urlpatterns = []
```

`core/__init__.py`: vuoto. `core/apps.py`:
```python
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Core"
```

`core/urls.py`:
```python
from django.urls import path

from . import views

app_name = "core"
urlpatterns = [
    path("", views.home, name="home"),
    path("stile/", views.stile, name="stile"),
]
```

`core/views.py` (provvisorio, le pagine vere arrivano nei Task 8 e 9):
```python
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse


@login_required
def home(request):
    return HttpResponse("home")


@login_required
def stile(request):
    return HttpResponse("stile")
```

- [ ] **Step 7: verifica**

Run: `pytest theme/tests/test_context.py -v && python manage.py check`
Expected: 2 passed; `System check identified no issues`.

- [ ] **Step 8: Commit**

```bash
git add requirements.txt requirements-dev.txt .env.example .gitignore pytest.ini manage.py config theme core
git commit -m "feat: impianto del progetto con settings via env, axes e app theme/core

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Token CSS, tema admin e favicon dinamica

**Files:**
- Create: `theme/static/theme/tokens.css`, `theme/static/theme/admin.css`
- Create: `theme/templates/admin/base_site.html`
- Create: `theme/views.py`, modify `theme/urls.py`
- Test: `theme/tests/test_admin.py`, `theme/tests/test_favicon.py`

- [ ] **Step 1: test (fallisce)**

`theme/tests/test_admin.py`:
```python
import pytest
from django.contrib.auth.models import User
from django.urls import reverse


@pytest.mark.django_db
def test_admin_index_ha_brand_e_css(client):
    User.objects.create_superuser("root", "root@example.com", "pass12345!")
    client.force_login(User.objects.get(username="root"))
    r = client.get(reverse("admin:index"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "theme/admin.css" in html
    assert "Progetto · Admin" in html
    assert 'class="ui-admin-mark">PR<' in html


@pytest.mark.django_db
def test_admin_login_usa_il_tema(client):
    r = client.get(reverse("admin:login"))
    assert r.status_code == 200
    assert "theme/admin.css" in r.content.decode()
```

`theme/tests/test_favicon.py`:
```python
from django.test import override_settings
from django.urls import reverse


def test_favicon_svg_con_sigla(client):
    with override_settings(THEME={"mark": "XY"}):
        r = client.get(reverse("theme:favicon"))
    assert r.status_code == 200
    assert r["Content-Type"] == "image/svg+xml"
    assert ">XY<" in r.content.decode()
```

Run: `pytest theme/tests/test_admin.py theme/tests/test_favicon.py -v`
Expected: FAIL (`NoReverseMatch: theme:favicon`, assert su `theme/admin.css`).

- [ ] **Step 2: tokens.css**

`theme/static/theme/tokens.css`:
```css
/* ============================================================
   Design token — l'UNICO posto dove si cambia la palette.
   Importato da admin.css e ui.css.
   ============================================================ */
:root {
  /* Brand (verificare contrasto AA >= 4.5:1 del primario su bianco) */
  --ui-primary: #1e3a8a;
  --ui-primary-lift: #2945a3;
  --ui-primary-hover-dark: #152a63;
  --ui-primary-hover-light: #243d94;
  --ui-primary-tint: rgba(30, 58, 138, 0.10);

  /* Testo */
  --ui-text: #1d1d1f;
  --ui-text-2: #6e6e73;
  --ui-text-3: #86868b;

  /* Superfici */
  --ui-surface: #ffffff;
  --ui-surface-2: #f5f5f7;
  --ui-border: #e5e5ea;
  --ui-border-soft: rgba(0, 0, 0, 0.10);

  /* Semantici */
  --ui-success: #34c759;
  --ui-warning: #ff9f0a;
  --ui-danger:  #ff3b30;
  --ui-success-tint: rgba(52, 199, 89, 0.12);
  --ui-warning-tint: rgba(255, 159, 10, 0.12);
  --ui-danger-tint:  rgba(255, 59, 48, 0.12);

  /* Raggi */
  --radius-card:  18px;
  --radius-modal: 12px;
  --radius-input: 8px;
  --radius-pill:  980px;

  /* Ombre */
  --shadow-card:     0 8px 30px rgba(0, 0, 0, 0.08);
  --shadow-header:   0 1px 3px rgba(0, 0, 0, 0.10);
  --shadow-dropdown: 0 8px 25px rgba(0, 0, 0, 0.10);
  --shadow-modal:    0 20px 40px rgba(0, 0, 0, 0.20);

  /* Tipografia: system stack, nessun webfont */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;

  /* Movimento */
  --ease-out: cubic-bezier(0.25, 0.46, 0.45, 0.94);
  --ease-bounce: cubic-bezier(0.175, 0.885, 0.32, 1.275);
  --transition: all 0.2s ease;
}
```

- [ ] **Step 3: admin.css (port meccanico di siee-admin.css)**

```bash
SRC=/home/adauser/part_dati/SIEE_Enas/prototype
OUT=theme/static/theme/admin.css
{
  echo '/* ============================================================'
  echo '   Tema admin Django 5.x — sovrascrive le custom property native.'
  echo '   I colori vengono da tokens.css.'
  echo '   ============================================================ */'
  echo '@import url("tokens.css");'
  echo
  # dalla riga 7 (":root,") in poi, saltando le 12 righe dei token brand (12-23)
  sed -n '7,11p' $SRC/static/admin/css/siee-admin.css
  sed -n '24,583p' $SRC/static/admin/css/siee-admin.css
} > $OUT
sed -i 's/--siee-/--ui-/g; s/siee-admin-mark/ui-admin-mark/g; s/siee-admin-brand/ui-admin-brand/g' $OUT
grep -n "siee" $OUT   # atteso: solo eventuali commenti; rinominali a mano in "ui"
```

Apri il file e controlla che il blocco `:root, :root[data-theme="light"], :root[data-theme="dark"] {` inizi con il commento `/* Override Django admin variables */` e contenga solo variabili `--primary`, `--body-*`, ecc. che puntano a `var(--ui-…)`. Se nelle righe 7-11 è rimasto un `/* Brand */` orfano, cancellalo.

- [ ] **Step 4: base_site.html**

`theme/templates/admin/base_site.html`:
```django
{% extends "admin/base.html" %}
{% load static %}

{% block title %}{{ subtitle }}{% if subtitle %} · {% endif %}{{ title }} · {{ theme.brand }}{% endblock %}

{% block extrastyle %}
  {{ block.super }}
  <link rel="stylesheet" href="{% static 'theme/admin.css' %}">
  <link rel="icon" type="image/svg+xml" href="{% url 'theme:favicon' %}">
{% endblock %}

{% block branding %}
<h1 id="site-name">
  <a href="{% url 'admin:index' %}">
    <span class="ui-admin-mark">{{ theme.mark }}</span>
    <span class="ui-admin-brand">{{ theme.brand }} · Admin</span>
  </a>
</h1>
{% endblock %}

{% block nav-global %}{% endblock %}
```

- [ ] **Step 5: favicon dinamica**

`theme/views.py`:
```python
from django.conf import settings
from django.http import HttpResponse
from django.utils.html import escape
from django.views.decorators.cache import cache_control

from .context_processors import DEFAULTS

SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="{bg}"/>'
    '<text x="32" y="41" text-anchor="middle" font-family="-apple-system,Segoe UI,Roboto,Arial,sans-serif" '
    'font-size="{size}" font-weight="700" fill="#fff">{mark}</text></svg>'
)


@cache_control(max_age=86400)
def favicon(request):
    """Badge quadrato con la sigla del brand, stesso look del badge nell'header."""
    mark = {**DEFAULTS, **getattr(settings, "THEME", {})}["mark"][:3]
    size = {1: 36, 2: 28, 3: 22}[max(1, len(mark))]
    svg = SVG.format(bg="#1e3a8a", size=size, mark=escape(mark))
    return HttpResponse(svg, content_type="image/svg+xml")
```

`theme/urls.py`:
```python
from django.urls import path

from . import views

app_name = "theme"
urlpatterns = [
    path("favicon.svg", views.favicon, name="favicon"),
]
```

Nota: il colore di sfondo della favicon è fisso (`#1e3a8a`) perché un SVG servito da view non legge `tokens.css`; chi cambia palette lo aggiorna qui (segnalato nel README, Task 11).

- [ ] **Step 6: verifica**

Run: `pytest theme/tests -v`
Expected: tutti PASS (context 2, admin 2, favicon 1).

- [ ] **Step 7: Commit**

```bash
git add theme
git commit -m "feat(theme): token CSS, tema admin e favicon con la sigla del brand

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: ui.css — componenti frontend portati da siee.css

**Files:**
- Create: `theme/static/theme/ui.css`
- Test: `theme/tests/test_css.py`

- [ ] **Step 1: test (fallisce)**

`theme/tests/test_css.py`:
```python
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "static" / "theme"

# Residui di SIEE che non devono comparire nel tema generico
VIETATI = [
    "siee", "--color-", "datatable", "ridisegnata", "brand-enas", "logo-mark img",
    "form-control", "form-select", "mega", "scope", "suggest", "kv-2col",
    "back-btn", "back-link", "impianto", "quickstart", "report", "htmx", "alpine",
]

CLASSI_RICHIESTE = [
    ".ui-body", ".ui-container", ".ui-header", ".ui-logo", ".ui-logo-mark", ".ui-nav",
    ".ui-nav-toggle", ".ui-dropdown", ".ui-profile-trigger", ".ui-avatar",
    ".ui-pagehead", ".ui-kpis", ".ui-kpi", ".ui-card", ".ui-card-head", ".ui-card-body",
    ".ui-btn", ".ui-btn-primary", ".ui-btn-secondary", ".ui-btn-ghost", ".ui-btn-danger",
    ".ui-btn-sm", ".ui-icon-btn", ".ui-input", ".ui-label", ".ui-form-group",
    ".ui-pill", ".ui-pill-ok", ".ui-pill-warn", ".ui-pill-danger", ".ui-pill-neutral",
    "table.ui-table", ".ui-empty", ".ui-alert", ".ui-alert-error", ".ui-login",
    ".ui-login-card", ".ui-footer", ".ui-toast", ".ui-link", ".ui-code",
]


def test_ui_css_senza_residui_siee():
    testo = (CSS / "ui.css").read_text().lower()
    presenti = [v for v in VIETATI if v in testo]
    assert presenti == [], f"residui SIEE in ui.css: {presenti}"


def test_ui_css_ha_le_classi_del_catalogo():
    testo = (CSS / "ui.css").read_text()
    mancanti = [c for c in CLASSI_RICHIESTE if c not in testo]
    assert mancanti == [], f"classi mancanti in ui.css: {mancanti}"


def test_admin_css_senza_residui_siee():
    testo = (CSS / "admin.css").read_text().lower()
    assert "siee" not in testo
```

Run: `pytest theme/tests/test_css.py -v`
Expected: FAIL (`ui.css` non esiste).

- [ ] **Step 2: estrazione meccanica da siee.css**

Gli intervalli di riga sono verificati su `siee.css` al commit `123d354` di SIEE (2096 righe). Se `wc -l` dà un numero diverso, cerca le intestazioni di sezione (`grep -n "^   [A-Z]" siee.css`) e riallinea.

```bash
SRC=/home/adauser/part_dati/SIEE_Enas/prototype/static/css/siee.css
OUT=theme/static/theme/ui.css
test "$(wc -l < $SRC)" = 2096 || echo "ATTENZIONE: siee.css cambiato, verifica gli intervalli"
{
  echo '/* ============================================================'
  echo '   Componenti frontend — i colori vengono da tokens.css.'
  echo '   Catalogo vivente: /stile/ nel progetto.'
  echo '   ============================================================ */'
  echo '@import url("tokens.css");'
  echo
  sed -n '67,100p'   $SRC   # reset/base + layout
  sed -n '101,193p'  $SRC   # header, nav, dropdown, logout
  sed -n '278,282p'  $SRC   # rotazione chevron del trigger
  sed -n '302,314p'  $SRC   # hamburger (nav toggle)
  sed -n '346,362p'  $SRC   # profilo + avatar
  sed -n '363,440p'  $SRC   # page head, KPI, card
  sed -n '441,568p'  $SRC   # bottoni, icon-btn, tooltip, kpi-link
  sed -n '579,591p'  $SRC   # delta pill
  sed -n '766,839p'  $SRC   # input, label, form-group (+ override bootstrap da togliere)
  sed -n '840,907p'  $SRC   # pill, code, tabelle, empty state
  sed -n '922,1031p' $SRC   # login, label-row, input-affix, footer
  sed -n '1164,1218p' $SRC  # animazioni tabelle/empty
  sed -n '1231,1271p' $SRC  # link grow + reduced motion override
  sed -n '1502,1512p' $SRC  # reduced motion globale
  sed -n '1641,1666p' $SRC  # toast
} > $OUT
```

- [ ] **Step 3: rinomina**

```bash
OUT=theme/static/theme/ui.css
sed -i \
  -e 's/--color-/--ui-/g' \
  -e 's/siee-logo-zap/ui-logo-mark-tmp/g' \
  -e 's/siee-row-in/ui-row-in/g; s/siee-empty-in/ui-empty-in/g' \
  -e 's/siee-/ui-/g' \
  -e 's/ui-logo-mark-tmp/ui-logo-mark/g' \
  $OUT
```

(Il giro su `logo-zap` serve perché in SIEE `.siee-logo-mark` era il contenitore del logo ENAS, che non portiamo, mentre `.siee-logo-zap` era il badge blu che diventa il nostro `.ui-logo-mark`.)

- [ ] **Step 4: pulizia a mano**

Apri `ui.css` e **cancella intere regole** (selettore + blocco `{…}`) e i commenti che le precedono quando il selettore contiene uno di questi testi:

- `.ui-logo-mark { height: 28px; … background: #04a7e8` e `.ui-logo-mark img` (le due regole del logo ENAS; **tieni** quella con `width: 28px; height: 28px; … background: var(--ui-primary)` che era `logo-zap`)
- `.ui-brand-enas`
- `ui-datatable` (2 regole nei bottoni)
- `.ui-nav-button` — in ogni selettore multiplo togli solo quella parte (es. `.ui-nav a, .ui-nav .ui-nav-button {` → `.ui-nav a {`); le regole con solo `.ui-nav-button` si cancellano
- `.form-control`, `.form-select`, `ui-search-input` (nell'intervallo input: tutto il blocco "Override Bootstrap inputs")
- `.ui-ridisegnata` (con il commento su DataTables)
- `.ui-login-marks`, `.ui-login-header .mark img`
- `.ui-logo-mark svg` (il badge ora contiene testo, non un'icona)
- qualunque commento che citi ENAS, DataTables, HTMX, Alpine, siee.js, impianti, fatture

Poi **sostituisci** la regola `.ui-login-header .mark { … }` con:
```css
.ui-login-header .mark {
  width: 56px; height: 56px; border-radius: 14px; margin: 0 auto 16px;
  background: var(--ui-primary); color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700; letter-spacing: -0.02em;
}
```

- [ ] **Step 5: blocchi scritti a mano (in coda al file)**

```css
/* ============================================================
   Badge sigla nell'header (testo, non icona)
   ============================================================ */
.ui-logo-mark { font-size: 11px; font-weight: 700; letter-spacing: -0.02em; }

/* ============================================================
   Alert (messages di Django: success, info, warning, error)
   ============================================================ */
.ui-alert {
  padding: 12px 16px; margin-bottom: 16px;
  border-radius: var(--radius-input);
  font-size: 14px; font-weight: 500;
  background: var(--ui-primary-tint); color: var(--ui-primary);
}
.ui-alert-info    { background: var(--ui-primary-tint); color: var(--ui-primary); }
.ui-alert-success { background: var(--ui-success-tint); color: #1f7a3a; }
.ui-alert-warning { background: var(--ui-warning-tint); color: #b46300; }
.ui-alert-danger,
.ui-alert-error   { background: var(--ui-danger-tint);  color: #c4271f; }

/* ============================================================
   Select e textarea con lo stesso look di .ui-input
   ============================================================ */
select.ui-input { appearance: auto; height: auto; }
textarea.ui-input { min-height: 96px; resize: vertical; }
.ui-help { display: block; margin-top: 6px; font-size: 12px; color: var(--ui-text-3); line-height: 1.4; }
.ui-form-error { margin-top: 6px; font-size: 12px; color: #c4271f; }

/* ============================================================
   Responsive (<= 767px): hamburger + nav verticale
   ============================================================ */
@media (max-width: 767px) {
  html, body { overflow-x: hidden; }
  .ui-header-inner { gap: 10px; }
  .ui-nav { display: none; }
  .ui-nav-toggle { display: inline-flex; }
  .ui-nav.is-open {
    display: flex; flex-direction: column; align-items: stretch; gap: 2px;
    position: fixed; top: 60px; left: 0; right: 0; z-index: 95;
    background: var(--ui-surface); border-top: 1px solid var(--ui-border);
    box-shadow: var(--shadow-card); padding: 12px 16px 20px;
  }
  .ui-nav.is-open a { padding: 12px 14px; font-size: 15px; border-radius: 10px; }
  .ui-nav.is-open a.is-active { background: var(--ui-primary-tint); }
  .ui-nav.is-open a.is-active::after { display: none; }
  .ui-logo { font-size: 15px; gap: 6px; white-space: nowrap; }
  .ui-logo-mark { width: 24px; height: 24px; font-size: 10px; }
  .ui-profile-name { display: none; }
  .ui-avatar { font-size: 11px; letter-spacing: 0.3px; }
  .ui-pagehead { flex-direction: column; align-items: flex-start; gap: 10px; }
  .ui-pagehead h1 { font-size: 18px; }
  .ui-card-head { flex-wrap: wrap; }
  table.ui-table th, table.ui-table td { padding: 12px 14px; }
  .ui-toast { left: 16px; right: 16px; max-width: none; }
}
```

- [ ] **Step 6: verifica**

Run: `pytest theme/tests/test_css.py -v`
Expected: 3 passed. Se `test_ui_css_senza_residui_siee` elenca residui, cercali con `grep -n -i "<residuo>" theme/static/theme/ui.css` e cancella la regola o il commento. Se mancano classi, controlla che la rinomina non abbia saltato un intervallo.

- [ ] **Step 7: Commit**

```bash
git add theme/static/theme/ui.css theme/tests/test_css.py
git commit -m "feat(theme): componenti frontend ui.css portati dallo stile SIEE

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: ui.js e sprite icone

**Files:**
- Create: `theme/static/theme/ui.js`
- Create: `theme/templates/theme/partials/_icons.html`
- Test: `theme/tests/test_icons.py`

- [ ] **Step 1: test (fallisce)**

`theme/tests/test_icons.py`:
```python
from pathlib import Path

ICONE = [
    "zap", "user", "lock", "tool", "chevron-down", "menu", "x", "check", "alert-triangle",
    "search", "arrow-left", "download", "log-out", "eye", "eye-off", "save", "plus",
    "edit", "trash", "inbox", "info",
]


def test_sprite_contiene_le_icone():
    html = (Path(__file__).resolve().parents[1] / "templates/theme/partials/_icons.html").read_text()
    mancanti = [i for i in ICONE if f'id="icon-{i}"' not in html]
    assert mancanti == []
    assert "siee" not in html.lower()
```

Run: `pytest theme/tests/test_icons.py -v`
Expected: FAIL (file mancante).

- [ ] **Step 2: estrai i simboli dallo sprite SIEE**

```bash
SRC=/home/adauser/part_dati/SIEE_Enas/prototype/core/templates/partials/_icons.html
python3 - "$SRC" theme/templates/theme/partials/_icons.html <<'EOF'
import re, sys
src, out = sys.argv[1], sys.argv[2]
keep = ["zap","user","lock","tool","chevron-down","menu","x","check","alert-triangle",
        "search","arrow-left","download","log-out","eye","eye-off","save","plus",
        "edit","trash","inbox","info"]
html = open(src).read()
symbols = {m.group(1): m.group(0)
           for m in re.finditer(r'<symbol id="icon-([a-z0-9-]+)".*?</symbol>', html, re.S)}
missing = [k for k in keep if k not in symbols]
assert not missing, missing
body = "\n".join("  " + symbols[k].strip() for k in keep)
open(out, "w").write(
    '{# Sprite SVG inline: usare con <svg><use href="#icon-nome"/></svg> #}\n'
    '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">\n'
    + body + "\n</svg>\n")
EOF
grep -ci siee theme/templates/theme/partials/_icons.html   # atteso 0
```

Se lo sprite sorgente usa `<g id=…>` invece di `<symbol>`, adatta la regex e verifica che ogni blocco estratto abbia `viewBox`.

- [ ] **Step 3: ui.js**

`theme/static/theme/ui.js`:
```js
/* ui.js — comportamenti minimi del tema: dropdown, menu mobile,
   mostra/nascondi password, ingresso righe tabella, toast. Nessuna dipendenza. */
(function () {
  'use strict';

  // --- Dropdown (.ui-dropdown > trigger[aria-controls] + .ui-dropdown-menu)
  const closeAllDropdowns = () => {
    document.querySelectorAll('.ui-dropdown.is-open').forEach((dd) => {
      dd.classList.remove('is-open');
      const t = dd.querySelector('[aria-haspopup]');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  };
  document.querySelectorAll('.ui-dropdown').forEach((dd) => {
    const trigger = dd.querySelector('[aria-haspopup]');
    if (!trigger) return;
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      const wasOpen = dd.classList.contains('is-open');
      closeAllDropdowns();
      if (!wasOpen) {
        dd.classList.add('is-open');
        trigger.setAttribute('aria-expanded', 'true');
      }
    });
    dd.querySelectorAll('.ui-dropdown-menu a, .ui-dropdown-menu button').forEach((el) => {
      el.addEventListener('click', () => {
        dd.classList.remove('is-open');
        trigger.setAttribute('aria-expanded', 'false');
      });
    });
  });
  document.addEventListener('click', closeAllDropdowns);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeAllDropdowns(); });

  // --- Menu mobile: il bottone .ui-nav-toggle apre/chiude .ui-nav
  const toggle = document.querySelector('.ui-nav-toggle');
  const nav = document.querySelector('.ui-nav');
  if (toggle && nav) {
    toggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = nav.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    document.addEventListener('click', () => {
      nav.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
    });
    nav.addEventListener('click', (e) => e.stopPropagation());
  }

  // --- Mostra/nascondi password: <button data-toggle-password="id_campo">
  document.querySelectorAll('[data-toggle-password]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const input = document.getElementById(btn.dataset.togglePassword);
      if (!input) return;
      const showing = input.type === 'text';
      input.type = showing ? 'password' : 'text';
      btn.setAttribute('aria-pressed', String(!showing));
      btn.setAttribute('aria-label', showing ? 'Mostra password' : 'Nascondi password');
      const eyeShow = btn.querySelector('[data-icon-show]');
      const eyeHide = btn.querySelector('[data-icon-hide]');
      if (eyeShow && eyeHide) { eyeShow.hidden = !showing; eyeHide.hidden = showing; }
    });
  });

  // --- Ingresso righe tabella: le righe partono invisibili (ui.css) e
  //     appaiono a cascata quando la tabella entra nel viewport.
  const tables = document.querySelectorAll('table.ui-table');
  const reveal = (t) => {
    t.querySelectorAll('tbody tr').forEach((tr, i) => tr.style.setProperty('--row-index', i));
    t.classList.add('is-revealed');
  };
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver((entries) => {
      entries.forEach((en) => { if (en.isIntersecting) { reveal(en.target); io.unobserve(en.target); } });
    }, { rootMargin: '0px 0px -10% 0px' });
    tables.forEach((t) => io.observe(t));
  } else {
    tables.forEach(reveal);
  }

  // --- Toast: window.uiToast('Salvato', 'warn'|undefined)
  window.uiToast = function (text, kind) {
    let el = document.querySelector('.ui-toast');
    if (!el) { el = document.createElement('div'); el.className = 'ui-toast'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
    el.textContent = text;
    el.classList.toggle('ui-toast-warn', kind === 'warn');
    requestAnimationFrame(() => el.classList.add('is-visible'));
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('is-visible'), 3000);
  };
})();
```

- [ ] **Step 4: verifica**

Run: `pytest theme/tests/test_icons.py -v && node -e "new Function(require('fs').readFileSync('theme/static/theme/ui.js','utf8'))" && echo JS_OK`
Expected: 1 passed; `JS_OK` (se `node` non è installato, salta il secondo controllo e verificalo nel browser al Task 11).

- [ ] **Step 5: Commit**

```bash
git add theme/static/theme/ui.js theme/templates/theme/partials/_icons.html theme/tests/test_icons.py
git commit -m "feat(theme): ui.js senza dipendenze e sprite icone

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Shell frontend — base.html, header, footer

**Files:**
- Create: `theme/templates/theme/base.html`, `theme/templates/theme/partials/_header.html`, `theme/templates/theme/partials/_footer.html`
- Test: `theme/tests/test_base.py`

- [ ] **Step 1: test (fallisce)**

`theme/tests/test_base.py`:
```python
import pytest
from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import RequestFactory, override_settings
from django.contrib.auth.models import AnonymousUser


def _render(user):
    tpl = Template("{% extends 'theme/base.html' %}{% block content %}CORPO{% endblock %}"
                   "{% block public_content %}PUBBLICO{% endblock %}")
    rf = RequestFactory()
    request = rf.get("/")
    request.user = user
    request.resolver_match = None
    from theme.context_processors import theme
    ctx = Context({"request": request, "user": user, **theme(request)})
    return tpl.render(ctx)


@pytest.mark.django_db
def test_utente_loggato_vede_header_nav_e_footer():
    user = User.objects.create_user("mario", "m@example.com", "pass12345!", first_name="Mario", last_name="Rossi")
    with override_settings(THEME={"brand": "Acme", "mark": "AC", "company": "Ichnobyte",
                                  "nav": [{"label": "Home", "url_name": "core:home"}]}):
        html = _render(user)
    assert "CORPO" in html and "PUBBLICO" not in html
    assert 'class="ui-logo-mark">AC<' in html
    assert ">Home<" in html
    assert "Mario Rossi" in html
    assert "Ichnobyte" in html
    assert "theme/ui.css" in html and "theme/ui.js" in html


def test_anonimo_vede_solo_public_content():
    html = _render(AnonymousUser())
    assert "PUBBLICO" in html and "CORPO" not in html
    assert "ui-header" not in html
```

Run: `pytest theme/tests/test_base.py -v`
Expected: FAIL (`TemplateDoesNotExist: theme/base.html`).

- [ ] **Step 2: base.html**

`theme/templates/theme/base.html`:
```django
{% load static %}<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}{{ theme.brand }}{% endblock %}</title>
  <link rel="stylesheet" href="{% static 'theme/ui.css' %}">
  <link rel="icon" type="image/svg+xml" href="{% url 'theme:favicon' %}">
  {% block head_extra %}{% endblock %}
</head>
<body class="ui-body">
  {% include 'theme/partials/_icons.html' %}

  {% if user.is_authenticated %}
    {% include 'theme/partials/_header.html' %}
    <main class="ui-shell">
      <div class="ui-container ui-content">
        {% if messages %}
          {% for m in messages %}<div class="ui-alert ui-alert-{{ m.tags|default:'info' }}">{{ m }}</div>{% endfor %}
        {% endif %}
        {% block content %}{% endblock %}
      </div>
    </main>
    {% include 'theme/partials/_footer.html' %}
  {% else %}
    {% block public_content %}{% endblock %}
  {% endif %}

  <script src="{% static 'theme/ui.js' %}"></script>
  {% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 3: header**

`theme/templates/theme/partials/_header.html`:
```django
{% with current=request.resolver_match.view_name|default:'' %}
<header class="ui-header">
  <div class="ui-container ui-header-inner">
    <a class="ui-logo" href="/">
      <span class="ui-logo-mark">{{ theme.mark }}</span>
      <span>{{ theme.brand }}</span>
    </a>

    <nav class="ui-nav" aria-label="Principale">
      {% for item in theme.nav %}
        <a href="{% url item.url_name %}" class="{% if current == item.url_name %}is-active{% endif %}">{{ item.label }}</a>
      {% endfor %}
    </nav>

    <button type="button" class="ui-nav-toggle" aria-label="Apri menu" aria-expanded="false">
      <svg><use href="#icon-menu"/></svg>
    </button>

    <div class="ui-profile">
      <div class="ui-dropdown">
        <button type="button" class="ui-profile-trigger" aria-haspopup="true" aria-expanded="false" aria-controls="profile-menu">
          <span class="ui-avatar">{{ user.username|slice:":1"|upper }}</span>
          <span class="ui-profile-name">{{ user.get_full_name|default:user.username }}</span>
          <svg class="chev" style="width:12px;height:12px;"><use href="#icon-chevron-down"/></svg>
        </button>
        <div id="profile-menu" class="ui-dropdown-menu is-right" role="menu">
          {% url 'core:profilo' as url_profilo %}
          {% if url_profilo %}<a href="{{ url_profilo }}"><svg><use href="#icon-user"/></svg> Profilo</a>{% endif %}
          <a href="{% url 'password_change' %}"><svg><use href="#icon-lock"/></svg> Cambia password</a>
          {% if user.is_staff %}
          <hr>
          <a href="{% url 'admin:index' %}"><svg><use href="#icon-tool"/></svg> Amministrazione</a>
          {% endif %}
          <hr>
          <form method="post" action="{% url 'logout' %}" class="ui-logout-form">
            {% csrf_token %}
            <button type="submit"><svg><use href="#icon-log-out"/></svg> Esci</button>
          </form>
        </div>
      </div>
    </div>
  </div>
</header>
{% endwith %}
```

Nota: `{% url 'core:profilo' as url_profilo %}` non solleva errore se la route non esiste (la forma `as` restituisce stringa vuota), così `theme/` resta indipendente da `core`.

- [ ] **Step 4: footer**

`theme/templates/theme/partials/_footer.html`:
```django
<footer class="ui-footer">
  <div class="ui-container ui-footer-inner">
    <span class="ui-footer-copy">
      © {% now "Y" %} {{ theme.brand }}{% if theme.company %} · Sviluppato da
      {% if theme.company_url %}<a href="{{ theme.company_url }}" target="_blank" rel="noopener">{{ theme.company }}</a>{% else %}{{ theme.company }}{% endif %}{% endif %}
    </span>
    {% if theme.version %}
    <nav class="ui-footer-links" aria-label="Footer">
      <span class="ui-footer-version ui-code">{{ theme.version }}</span>
    </nav>
    {% endif %}
  </div>
</footer>
```

- [ ] **Step 5: verifica**

Run: `pytest theme/tests/test_base.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add theme/templates/theme theme/tests/test_base.py
git commit -m "feat(theme): shell frontend con header, nav da settings e footer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Login, cambio password, lockout, pagine d'errore

**Files:**
- Create: `theme/templates/registration/login.html`, `theme/templates/registration/password_change_form.html`, `theme/templates/registration/password_change_done.html`, `theme/templates/lockout.html`
- Create: `theme/templates/theme/partials/_scheda_errore.html`, `theme/templates/400.html`, `403.html`, `404.html`, `500.html`, `403_csrf.html`
- Test: `theme/tests/test_pagine.py`

- [ ] **Step 1: test (fallisce)**

`theme/tests/test_pagine.py`:
```python
import pytest
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse


@pytest.mark.django_db
def test_login_in_stile_con_brand(client):
    with override_settings(THEME={"brand": "Acme", "mark": "AC"}):
        r = client.get(reverse("login"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "ui-login-card" in html
    assert '<span class="mark">AC</span>' in html
    assert "Acme" in html


@pytest.mark.django_db
def test_login_errato_mostra_alert(client):
    r = client.post(reverse("login"), {"username": "x", "password": "y"})
    assert r.status_code == 200
    assert "Credenziali non valide" in r.content.decode()


@pytest.mark.django_db
def test_cambio_password_richiede_login_e_usa_tema(client):
    r = client.get(reverse("password_change"))
    assert r.status_code == 302
    u = User.objects.create_user("anna", "a@example.com", "pass12345!")
    client.force_login(u)
    r = client.get(reverse("password_change"))
    assert r.status_code == 200
    assert "ui-card" in r.content.decode()


@pytest.mark.django_db
def test_404_usa_il_tema(client):
    r = client.get("/pagina-che-non-esiste/")
    assert r.status_code == 404
    assert "ui-card" in r.content.decode()
```

Run: `pytest theme/tests/test_pagine.py -v`
Expected: FAIL (`TemplateDoesNotExist: registration/login.html`; il 404 restituisce la pagina di default senza `ui-card`).

- [ ] **Step 2: login.html**

(Login e lockout condividono 8 righe di markup della card: si duplicano, una partial con blocchi parametrici sarebbe meno leggibile.)

`theme/templates/registration/login.html`:
```django
{% extends 'theme/base.html' %}
{% block title %}Accedi · {{ theme.brand }}{% endblock %}
{% block public_content %}
<div class="ui-login">
  <div class="ui-login-card">
    <div class="ui-login-header">
      <span class="mark">{{ theme.mark }}</span>
      <h1>{{ theme.brand }}</h1>
      <p>Accedi con le tue credenziali</p>
    </div>
    <form method="post" class="ui-login-body">
      {% csrf_token %}
      {% if form.errors %}<div class="ui-alert ui-alert-danger">Credenziali non valide.</div>{% endif %}
      {% if messages %}{% for m in messages %}<div class="ui-alert ui-alert-{{ m.tags|default:'info' }}">{{ m }}</div>{% endfor %}{% endif %}
      <div class="ui-form-group">
        <label class="ui-label" for="id_username">Username</label>
        <input class="ui-input" id="id_username" name="username" required autofocus
               autocapitalize="none" autocorrect="off" spellcheck="false" autocomplete="username">
      </div>
      <div class="ui-form-group">
        <label class="ui-label" for="id_password">Password</label>
        <div class="ui-input-affix">
          <input class="ui-input" id="id_password" name="password" type="password" required autocomplete="current-password">
          <button type="button" class="ui-input-affix-btn" data-toggle-password="id_password"
                  aria-label="Mostra password" aria-pressed="false">
            <svg data-icon-show width="18" height="18" viewBox="0 0 24 24"><use href="#icon-eye"/></svg>
            <svg data-icon-hide width="18" height="18" viewBox="0 0 24 24" hidden><use href="#icon-eye-off"/></svg>
          </button>
        </div>
      </div>
      <input type="hidden" name="next" value="{{ next }}">
      <button class="ui-btn ui-btn-primary" type="submit" style="width:100%; justify-content:center; margin-top:8px;">Accedi</button>
    </form>
  </div>
  {% if theme.version %}<p class="ui-login-version">versione {{ theme.version }}</p>{% endif %}
</div>
{% endblock %}
```

- [ ] **Step 3: lockout.html**

`theme/templates/lockout.html` (axes passa `cooloff_timedelta` nel contesto):
```django
{% extends 'theme/base.html' %}
{% block title %}Accesso bloccato · {{ theme.brand }}{% endblock %}
{% block public_content %}
<div class="ui-login">
  <div class="ui-login-card">
    <div class="ui-login-header">
      <span class="mark">{{ theme.mark }}</span>
      <h1>{{ theme.brand }}</h1>
    </div>
    <div class="ui-login-body">
      <div class="ui-alert ui-alert-danger">
        Troppi tentativi di accesso falliti. Riprova tra {{ cooloff_timedelta|default:"qualche minuto" }}.
      </div>
      <a class="ui-btn ui-btn-primary" href="{% url 'login' %}" style="width:100%; justify-content:center; margin-top:8px;">Torna al login</a>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: cambio password**

`theme/templates/registration/password_change_form.html`:
```django
{% extends 'theme/base.html' %}
{% block title %}Cambia password · {{ theme.brand }}{% endblock %}
{% block content %}
<div class="ui-pagehead">
  <div>
    <h1>Cambia password</h1>
    <div class="sub">Aggiorna la password del tuo account</div>
  </div>
</div>
<div class="ui-card" style="max-width:560px;">
  <div class="ui-card-body">
    <form method="post">
      {% csrf_token %}
      {% if form.errors %}
      <div class="ui-alert ui-alert-danger" role="alert">
        {% for field, errors in form.errors.items %}{% for error in errors %}<div>{{ error }}</div>{% endfor %}{% endfor %}
      </div>
      {% endif %}
      <div class="ui-form-group">
        <label class="ui-label" for="id_old_password">Password attuale</label>
        <div class="ui-input-affix">
          <input type="password" name="old_password" id="id_old_password" class="ui-input" required autofocus autocomplete="current-password">
          <button type="button" class="ui-input-affix-btn" data-toggle-password="id_old_password" aria-label="Mostra password" aria-pressed="false">
            <svg data-icon-show width="18" height="18" viewBox="0 0 24 24"><use href="#icon-eye"/></svg>
            <svg data-icon-hide width="18" height="18" viewBox="0 0 24 24" hidden><use href="#icon-eye-off"/></svg>
          </button>
        </div>
      </div>
      <div class="ui-form-group">
        <label class="ui-label" for="id_new_password1">Nuova password</label>
        <div class="ui-input-affix">
          <input type="password" name="new_password1" id="id_new_password1" class="ui-input" required autocomplete="new-password">
          <button type="button" class="ui-input-affix-btn" data-toggle-password="id_new_password1" aria-label="Mostra password" aria-pressed="false">
            <svg data-icon-show width="18" height="18" viewBox="0 0 24 24"><use href="#icon-eye"/></svg>
            <svg data-icon-hide width="18" height="18" viewBox="0 0 24 24" hidden><use href="#icon-eye-off"/></svg>
          </button>
        </div>
        <small class="ui-help">Almeno 8 caratteri, non solo numerica, non troppo simile ai tuoi dati.</small>
      </div>
      <div class="ui-form-group" style="margin-bottom:24px;">
        <label class="ui-label" for="id_new_password2">Conferma nuova password</label>
        <div class="ui-input-affix">
          <input type="password" name="new_password2" id="id_new_password2" class="ui-input" required autocomplete="new-password">
          <button type="button" class="ui-input-affix-btn" data-toggle-password="id_new_password2" aria-label="Mostra password" aria-pressed="false">
            <svg data-icon-show width="18" height="18" viewBox="0 0 24 24"><use href="#icon-eye"/></svg>
            <svg data-icon-hide width="18" height="18" viewBox="0 0 24 24" hidden><use href="#icon-eye-off"/></svg>
          </button>
        </div>
      </div>
      <div style="display:flex; gap:8px;">
        <button type="submit" class="ui-btn ui-btn-primary"><svg><use href="#icon-save"/></svg> Aggiorna password</button>
        <a href="/" class="ui-btn ui-btn-ghost">Annulla</a>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

`theme/templates/registration/password_change_done.html`:
```django
{% extends 'theme/base.html' %}
{% block title %}Password aggiornata · {{ theme.brand }}{% endblock %}
{% block content %}
<div class="ui-card" style="max-width:560px;">
  <div class="ui-card-body">
    <div class="ui-alert ui-alert-success">Password aggiornata correttamente.</div>
    <a href="/" class="ui-btn ui-btn-primary">Torna alla home</a>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: pagine d'errore**

`theme/templates/theme/partials/_scheda_errore.html`:
```django
<div class="ui-card" style="max-width:560px;margin:48px auto;text-align:center;">
  <div class="ui-card-body" style="padding:48px 28px;">
    <div style="font-size:56px;font-weight:700;color:var(--ui-text-3);line-height:1;">{{ codice }}</div>
    <h1 style="margin:12px 0 8px;font-size:20px;">{{ titolo }}</h1>
    <p style="color:var(--ui-text-3);margin:0 0 24px;">{{ testo }}</p>
    <a class="ui-btn ui-btn-primary" href="/">Torna alla home</a>
  </div>
</div>
```

`400.html`, `403.html`, `403_csrf.html` e `404.html` hanno la stessa forma; ecco `404.html`, le altre cambiano solo i tre valori (`500.html` è a parte, vedi sotto):
```django
{% extends 'theme/base.html' %}
{% block title %}Pagina non trovata · {{ theme.brand }}{% endblock %}
{% block content %}{% include 'theme/partials/_scheda_errore.html' with codice='404' titolo='Pagina non trovata' testo='La pagina che cerchi non esiste o è stata spostata.' %}{% endblock %}
{% block public_content %}<main class="ui-shell"><div class="ui-container ui-content">{% include 'theme/partials/_scheda_errore.html' with codice='404' titolo='Pagina non trovata' testo='La pagina che cerchi non esiste o è stata spostata.' %}</div></main>{% endblock %}
```

| File | codice | titolo | testo |
|---|---|---|---|
| `400.html` | 400 | Richiesta non valida | La richiesta non è stata compresa dal server. |
| `403.html` | 403 | Accesso negato | Non hai i permessi per vedere questa pagina. |
| `403_csrf.html` | 403 | Sessione scaduta | Il modulo è scaduto. Torna indietro, ricarica la pagina e riprova. |
| `404.html` | 404 | Pagina non trovata | La pagina che cerchi non esiste o è stata spostata. |
| `500.html` | 500 | Errore del server | Si è verificato un errore. Riprova tra qualche minuto. |

`500.html` è un caso a parte: la vista `server_error` di Django renderizza il template con un contesto vuoto, **senza** context processor, quindi `theme.*` e `user` non esistono. Non deve estendere `theme/base.html`: è una pagina autonoma che carica solo il CSS:
```django
{% load static %}<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Errore del server</title><link rel="stylesheet" href="{% static 'theme/ui.css' %}"></head>
<body class="ui-body"><main class="ui-shell"><div class="ui-container ui-content">
{% include 'theme/partials/_scheda_errore.html' with codice='500' titolo='Errore del server' testo='Si è verificato un errore. Riprova tra qualche minuto.' %}
</div></main></body></html>
```

- [ ] **Step 6: verifica**

Run: `pytest theme/tests -v`
Expected: tutti PASS.

- [ ] **Step 7: Commit**

```bash
git add theme/templates theme/tests/test_pagine.py
git commit -m "feat(theme): login, cambio password, lockout e pagine d'errore in stile

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Test di portabilità di `theme/` e dei flag di produzione

**Files:**
- Create: `theme/tests/test_portabilita.py`
- Create: `config/tests/__init__.py`, `config/tests/test_settings.py`

- [ ] **Step 1: test portabilità**

`theme/tests/test_portabilita.py`:
```python
import re
from pathlib import Path

THEME = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"^\s*(from|import)\s+(core|config)\b", re.M)


def test_theme_non_importa_core_ne_config():
    colpevoli = []
    for p in THEME.rglob("*.py"):
        if "tests" in p.parts:
            continue
        if PATTERN.search(p.read_text()):
            colpevoli.append(str(p.relative_to(THEME)))
    assert colpevoli == []


def test_template_theme_non_usano_url_di_core_senza_as():
    """`{% url 'core:x' %}` secco romperebbe un progetto senza core;
    la forma `{% url 'core:x' as var %}` è tollerata."""
    colpevoli = []
    for p in (THEME / "templates").rglob("*.html"):
        for riga in p.read_text().splitlines():
            if "{% url 'core:" in riga and " as " not in riga:
                colpevoli.append(f"{p.name}: {riga.strip()}")
    assert colpevoli == []
```

Run: `pytest theme/tests/test_portabilita.py -v`
Expected: 2 passed (se fallisce, sistemare il file indicato, non il test).

- [ ] **Step 2: test flag di produzione**

`config/tests/__init__.py`: vuoto.

`config/tests/test_settings.py`:
```python
import importlib
import os
from unittest import mock


def _carica(debug):
    env = {"DEBUG": debug, "SECRET_KEY": "x", "SECURE_HSTS_SECONDS": "0"}
    with mock.patch.dict(os.environ, env, clear=False):
        import config.settings as s
        return importlib.reload(s)


def test_con_debug_false_cookie_secure_e_proxy_header():
    s = _carica("False")
    assert s.DEBUG is False
    assert s.SESSION_COOKIE_SECURE is True
    assert s.CSRF_COOKIE_SECURE is True
    assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert s.SECURE_HSTS_SECONDS == 0
    assert "file_app" in s.LOGGING["handlers"]
    assert "file_error" in s.LOGGING["handlers"]


def test_con_debug_true_niente_flag_di_produzione():
    s = _carica("True")
    assert s.DEBUG is True
    assert not hasattr(s, "SECURE_PROXY_SSL_HEADER")
    assert "file_app" not in s.LOGGING["handlers"]


def test_sicurezza_sempre_attiva():
    s = _carica("True")
    assert s.X_FRAME_OPTIONS == "DENY"
    assert s.SESSION_COOKIE_HTTPONLY is True
    assert s.AXES_FAILURE_LIMIT == 5
    assert s.AXES_LOCKOUT_TEMPLATE == "lockout.html"
    assert s.AUTHENTICATION_BACKENDS[0] == "axes.backends.AxesStandaloneBackend"
```

Attenzione: `importlib.reload` di `config.settings` tocca il modulo ma non `django.conf.settings` (già caricato da pytest-django): i test restano isolati. Il reload con `DEBUG=False` crea la cartella `logs/` (ignorata da git).

Run: `pytest config/tests -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add theme/tests/test_portabilita.py config/tests
git commit -m "test: portabilità di theme e flag di produzione dei settings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: core — modello Cliente, admin, home

**Files:**
- Create: `core/models.py`, `core/admin.py`, `core/migrations/0001_initial.py` (generata)
- Modify: `core/views.py`
- Create: `core/templates/core/home.html`
- Test: `core/tests/__init__.py`, `core/tests/test_pagine.py`

- [ ] **Step 1: test (fallisce)**

`core/tests/__init__.py`: vuoto.

`core/tests/test_pagine.py`:
```python
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from core.models import Cliente


@pytest.fixture
def staff(client):
    u = User.objects.create_user("staff", "s@example.com", "pass12345!", is_staff=True, is_superuser=True)
    client.force_login(u)
    return u


@pytest.mark.django_db
def test_home_richiede_login(client):
    r = client.get(reverse("core:home"))
    assert r.status_code == 302
    assert r["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_home_mostra_kpi_e_tabella(client, staff):
    Cliente.objects.create(nome="Rossi Srl", email="info@rossi.it", attivo=True)
    Cliente.objects.create(nome="Bianchi Spa", email="info@bianchi.it", attivo=False)
    r = client.get(reverse("core:home"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "ui-kpis" in html and "ui-table" in html
    assert "Rossi Srl" in html and "Bianchi Spa" in html
    assert "Progetto" in html  # brand dal THEME di default dei settings


@pytest.mark.django_db
def test_home_vuota_mostra_empty_state(client, staff):
    r = client.get(reverse("core:home"))
    assert "ui-empty" in r.content.decode()


@pytest.mark.django_db
def test_admin_cliente_changelist_e_change(client, staff):
    c = Cliente.objects.create(nome="Verdi", email="v@example.com")
    assert client.get(reverse("admin:core_cliente_changelist")).status_code == 200
    assert client.get(reverse("admin:core_cliente_change", args=[c.pk])).status_code == 200
    assert client.get(reverse("admin:core_cliente_add")).status_code == 200
```

Run: `pytest core/tests/test_pagine.py -v`
Expected: FAIL (`ImportError: cannot import name 'Cliente'`).

- [ ] **Step 2: modello e admin**

`core/models.py`:
```python
from django.db import models


class Cliente(models.Model):
    """Modello di esempio: serve solo a mostrare admin e tabelle con dati veri."""
    nome = models.CharField("nome", max_length=120)
    email = models.EmailField("email", blank=True)
    attivo = models.BooleanField("attivo", default=True)
    note = models.TextField("note", blank=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clienti"
        ordering = ["-creato"]

    def __str__(self):
        return self.nome
```

`core/admin.py`:
```python
from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nome", "email", "attivo", "creato")
    list_filter = ("attivo", "creato")
    search_fields = ("nome", "email")
    date_hierarchy = "creato"
    list_per_page = 25
    fieldsets = (
        (None, {"fields": ("nome", "email", "attivo")}),
        ("Altro", {"fields": ("note",), "classes": ("collapse",)}),
    )
```

Run: `python manage.py makemigrations core`
Expected: `core/migrations/0001_initial.py` creato.

- [ ] **Step 3: home view e template**

`core/views.py` (sostituisce il provvisorio; `stile` resta provvisoria fino al Task 9):
```python
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from .models import Cliente


@login_required
def home(request):
    qs = Cliente.objects.all()
    da_30_giorni = timezone.now() - timedelta(days=30)
    ctx = {
        "totale": qs.count(),
        "attivi": qs.filter(attivo=True).count(),
        "recenti": qs.filter(creato__gte=da_30_giorni).count(),
        "ultimi": qs[:10],
    }
    return render(request, "core/home.html", ctx)


@login_required
def stile(request):
    return HttpResponse("stile")
```

`core/templates/core/home.html`:
```django
{% extends 'theme/base.html' %}
{% load humanize %}
{% block title %}Home · {{ theme.brand }}{% endblock %}
{% block content %}
<div class="ui-pagehead">
  <div>
    <h1>Benvenuto, {{ user.first_name|default:user.username }}</h1>
    <div class="sub">Panoramica di {{ theme.brand }}</div>
  </div>
  <div class="ui-pagehead-actions">
    {% if user.is_staff %}<a class="ui-btn ui-btn-primary" href="{% url 'admin:core_cliente_add' %}"><svg><use href="#icon-plus"/></svg> Nuovo cliente</a>{% endif %}
  </div>
</div>

<div class="ui-kpis">
  <div class="ui-kpi"><div class="label">Clienti</div><div class="value">{{ totale|intcomma }}</div><div class="sub">totali</div></div>
  <div class="ui-kpi"><div class="label">Attivi</div><div class="value">{{ attivi|intcomma }}</div><div class="sub">con stato attivo</div></div>
  <div class="ui-kpi"><div class="label">Nuovi</div><div class="value">{{ recenti|intcomma }}</div><div class="sub">ultimi 30 giorni</div></div>
</div>

<div class="ui-card is-revealed">
  <div class="ui-card-head">
    <div><div class="ui-card-title">Ultimi clienti</div><div class="ui-card-sub">I 10 inseriti più di recente</div></div>
    <div class="spacer"></div>
  </div>
  {% if ultimi %}
  <table class="ui-table">
    <thead><tr><th>Nome</th><th>Email</th><th>Stato</th><th>Creato</th></tr></thead>
    <tbody>
      {% for c in ultimi %}
      <tr>
        <td>{{ c.nome }}</td>
        <td>{{ c.email|default:"—" }}</td>
        <td>{% if c.attivo %}<span class="ui-pill ui-pill-ok">Attivo</span>{% else %}<span class="ui-pill ui-pill-neutral">Non attivo</span>{% endif %}</td>
        <td>{{ c.creato|date:"d/m/Y" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="ui-card-body">
    <div class="ui-empty"><svg><use href="#icon-inbox"/></svg><p>Nessun cliente ancora. Aggiungine uno dall'amministrazione.</p></div>
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 4: verifica**

Run: `pytest core/tests/test_pagine.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core
git commit -m "feat(core): modello Cliente di esempio, admin e home con KPI e tabella

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: core — catalogo dello stile e profilo

**Files:**
- Create: `core/forms.py`, `core/templates/core/stile.html`, `core/templates/core/profilo.html`
- Modify: `core/views.py`, `core/urls.py`
- Test: `core/tests/test_pagine.py` (aggiunte)

- [ ] **Step 1: test (fallisce)**

Aggiungi in fondo a `core/tests/test_pagine.py`:
```python
@pytest.mark.django_db
def test_catalogo_stile_mostra_ogni_componente(client, staff):
    r = client.get(reverse("core:stile"))
    assert r.status_code == 200
    html = r.content.decode()
    for classe in ["ui-btn-primary", "ui-btn-secondary", "ui-btn-ghost", "ui-btn-danger",
                   "ui-icon-btn", "ui-input", "ui-pill-ok", "ui-pill-warn", "ui-pill-danger",
                   "ui-kpi", "ui-card", "ui-table", "ui-empty", "ui-alert-success", "ui-link"]:
        assert classe in html, classe
    assert "uiToast(" in html
    assert "<pre" in html  # snippet da copiare


@pytest.mark.django_db
def test_profilo_modifica_nome(client, staff):
    r = client.get(reverse("core:profilo"))
    assert r.status_code == 200
    r = client.post(reverse("core:profilo"), {"first_name": "Anna", "last_name": "Neri", "email": "a@n.it"})
    assert r.status_code == 302
    staff.refresh_from_db()
    assert staff.first_name == "Anna" and staff.email == "a@n.it"
```

Run: `pytest core/tests/test_pagine.py -v -k "stile or profilo"`
Expected: FAIL (`NoReverseMatch: core:profilo`; stile senza componenti).

- [ ] **Step 2: form e view**

`core/forms.py`:
```python
from django import forms
from django.contrib.auth.models import User


class ProfiloForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        labels = {"first_name": "Nome", "last_name": "Cognome", "email": "Email"}
        widgets = {f: forms.TextInput(attrs={"class": "ui-input"}) for f in ["first_name", "last_name"]}
        widgets["email"] = forms.EmailInput(attrs={"class": "ui-input"})
```

Sostituisci la `stile` provvisoria in `core/views.py` e aggiungi `profilo`:
```python
from django.contrib import messages
from django.shortcuts import redirect

from .forms import ProfiloForm


@login_required
def stile(request):
    return render(request, "core/stile.html")


@login_required
def profilo(request):
    form = ProfiloForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profilo aggiornato.")
        return redirect("core:profilo")
    return render(request, "core/profilo.html", {"form": form})
```
(Togli `from django.http import HttpResponse`, non serve più.)

`core/urls.py`, aggiungi: `path("profilo/", views.profilo, name="profilo"),`

- [ ] **Step 3: profilo.html**

`core/templates/core/profilo.html`:
```django
{% extends 'theme/base.html' %}
{% block title %}Profilo · {{ theme.brand }}{% endblock %}
{% block content %}
<div class="ui-pagehead"><div><h1>Profilo</h1><div class="sub">{{ user.username }}</div></div></div>
<div class="ui-card is-revealed" style="max-width:560px;">
  <div class="ui-card-body">
    <form method="post">
      {% csrf_token %}
      {% for field in form %}
      <div class="ui-form-group">
        <label class="ui-label" for="{{ field.id_for_label }}">{{ field.label }}</label>
        {{ field }}
        {% for e in field.errors %}<div class="ui-form-error">{{ e }}</div>{% endfor %}
      </div>
      {% endfor %}
      <div style="display:flex; gap:8px; margin-top:24px;">
        <button type="submit" class="ui-btn ui-btn-primary"><svg><use href="#icon-save"/></svg> Salva</button>
        <a href="{% url 'password_change' %}" class="ui-btn ui-btn-secondary"><svg><use href="#icon-lock"/></svg> Cambia password</a>
      </div>
    </form>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 4: stile.html (catalogo)**

Ogni sezione è una card con l'esempio renderizzato e sotto un `<pre class="ui-code">` con lo stesso HTML (escapato con `{% filter force_escape %}`). Scrivi `core/templates/core/stile.html` con **tutte** queste sezioni, nell'ordine; per ognuna la struttura è:

```django
<div class="ui-card is-revealed">
  <div class="ui-card-head"><div class="ui-card-title">NOME SEZIONE</div></div>
  <div class="ui-card-body">
    ESEMPIO RENDERIZZATO
    <pre class="ui-code" style="margin-top:16px;padding:12px 14px;background:var(--ui-surface-2);border-radius:var(--radius-input);overflow:auto;font-size:12px;">{% filter force_escape %}ESEMPIO (stesso HTML){% endfilter %}</pre>
  </div>
</div>
```

Sezioni ed esempi (l'HTML dell'esempio va sia renderizzato sia dentro il `<pre>`):

1. **Bottoni**
```html
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
  <button class="ui-btn ui-btn-primary">Primario</button>
  <button class="ui-btn ui-btn-secondary">Secondario</button>
  <button class="ui-btn ui-btn-ghost">Ghost</button>
  <button class="ui-btn ui-btn-danger">Elimina</button>
  <button class="ui-btn ui-btn-primary ui-btn-sm"><svg><use href="#icon-plus"/></svg> Piccolo</button>
  <button class="ui-btn ui-btn-primary" disabled>Disabilitato</button>
  <button class="ui-icon-btn" data-tooltip="Modifica"><svg><use href="#icon-edit"/></svg></button>
  <button class="ui-icon-btn ui-icon-btn-danger" data-tooltip="Elimina"><svg><use href="#icon-trash"/></svg></button>
</div>
```
2. **Campi**
```html
<div class="ui-form-group"><label class="ui-label" for="es-nome">Nome</label><input class="ui-input" id="es-nome" placeholder="Es. Rossi Srl"></div>
<div class="ui-form-group"><label class="ui-label" for="es-stato">Stato</label><select class="ui-input" id="es-stato"><option>Attivo</option><option>Sospeso</option></select></div>
<div class="ui-form-group"><label class="ui-label" for="es-note">Note</label><textarea class="ui-input" id="es-note"></textarea><small class="ui-help">Testo di aiuto sotto al campo.</small></div>
```
3. **Pill**
```html
<span class="ui-pill ui-pill-ok">Attivo</span> <span class="ui-pill ui-pill-warn">In attesa</span>
<span class="ui-pill ui-pill-danger">Errore</span> <span class="ui-pill ui-pill-neutral">Bozza</span>
<span class="ui-pill ui-pill-info">Info</span> <code class="ui-code">ABC-123</code>
```
4. **KPI**
```html
<div class="ui-kpis">
  <div class="ui-kpi"><div class="label">Fatturato</div><div class="value">12.480 €</div><div class="sub">mese corrente</div></div>
  <div class="ui-kpi"><div class="label">Ordini</div><div class="value">37</div><div class="sub">+4 rispetto a ieri</div></div>
</div>
```
5. **Tabella**
```html
<table class="ui-table">
  <thead><tr><th>Nome</th><th>Stato</th><th class="actions"></th></tr></thead>
  <tbody>
    <tr><td>Rossi Srl</td><td><span class="ui-pill ui-pill-ok">Attivo</span></td><td class="actions"><button class="ui-icon-btn" data-tooltip="Modifica"><svg><use href="#icon-edit"/></svg></button></td></tr>
    <tr><td>Bianchi Spa</td><td><span class="ui-pill ui-pill-neutral">Bozza</span></td><td class="actions"><button class="ui-icon-btn" data-tooltip="Modifica"><svg><use href="#icon-edit"/></svg></button></td></tr>
  </tbody>
</table>
```
6. **Empty state**
```html
<div class="ui-empty"><svg><use href="#icon-inbox"/></svg><p>Nessun elemento da mostrare.</p></div>
```
7. **Alert e toast**
```html
<div class="ui-alert ui-alert-success">Operazione completata.</div>
<div class="ui-alert ui-alert-warning">Attenzione: controlla i dati.</div>
<div class="ui-alert ui-alert-error">Qualcosa è andato storto.</div>
<button class="ui-btn ui-btn-secondary" onclick="uiToast('Salvato')">Mostra toast</button>
<button class="ui-btn ui-btn-secondary" onclick="uiToast('Attenzione', 'warn')">Toast di avviso</button>
```
8. **Link e card**
```html
<p>Un <a class="ui-link" href="#">link con sottolineatura animata</a> dentro un paragrafo.</p>
<div class="ui-card is-revealed"><div class="ui-card-head"><div><div class="ui-card-title">Titolo card</div><div class="ui-card-sub">Sottotitolo</div></div><div class="spacer"></div><div class="head-actions"><button class="ui-btn ui-btn-ghost ui-btn-sm">Azione</button></div></div><div class="ui-card-body">Contenuto.</div></div>
```

In testa alla pagina: `{% extends 'theme/base.html' %}`, `{% block title %}Stile · {{ theme.brand }}{% endblock %}`, e un `ui-pagehead` con h1 "Catalogo dello stile" e sub "Ogni componente di ui.css con lo snippet da copiare".

- [ ] **Step 5: verifica**

Run: `pytest -v`
Expected: tutti PASS (theme, config, core).

- [ ] **Step 6: Commit**

```bash
git add core
git commit -m "feat(core): catalogo dello stile e pagina profilo

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10: Blocco axes (test end-to-end)

**Files:**
- Test: `core/tests/test_axes.py`

- [ ] **Step 1: test**

`core/tests/test_axes.py`:
```python
import pytest
from django.contrib.auth.models import User
from django.urls import reverse


@pytest.mark.django_db
def test_dopo_5_tentativi_falliti_arriva_il_lockout(client):
    User.objects.create_user("mario", "m@example.com", "giusta12345!")
    url = reverse("login")
    for _ in range(5):
        r = client.post(url, {"username": "mario", "password": "sbagliata"}, REMOTE_ADDR="10.0.0.9")
        assert r.status_code == 200
    r = client.post(url, {"username": "mario", "password": "giusta12345!"}, REMOTE_ADDR="10.0.0.9")
    assert r.status_code == 403
    assert "lockout.html" in [t.name for t in r.templates]
    assert "Troppi tentativi" in r.content.decode()


@pytest.mark.django_db
def test_altro_ip_non_e_bloccato(client):
    User.objects.create_user("mario", "m@example.com", "giusta12345!")
    url = reverse("login")
    for _ in range(5):
        client.post(url, {"username": "mario", "password": "sbagliata"}, REMOTE_ADDR="10.0.0.9")
    r = client.post(url, {"username": "mario", "password": "giusta12345!"}, REMOTE_ADDR="10.0.0.10")
    assert r.status_code == 302  # login riuscito
```

Run: `pytest core/tests/test_axes.py -v`
Expected: 2 passed. Se il primo fallisce con 200 invece di 403, controlla che `axes.middleware.AxesMiddleware` sia in `MIDDLEWARE` e `AxesStandaloneBackend` primo in `AUTHENTICATION_BACKENDS` (Task 1). Se axes lamenta la cache, aggiungi ai settings `AXES_HANDLER = "axes.handlers.database.AxesDatabaseHandler"` (è il default, ma rende esplicito).

- [ ] **Step 2: Commit**

```bash
git add core/tests/test_axes.py
git commit -m "test(core): blocco login dopo 5 tentativi con django-axes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11: README e verifica manuale nel browser

**Files:**
- Create: `README.md`

- [ ] **Step 1: README**

`README.md`:
````markdown
# django-template

Starter Django 5.2 con lo stile grafico "SaaS" di ICHNOBYTE (admin e frontend)
e la sicurezza di base già configurata. Si clona per iniziare un nuovo cliente.

## Avvio in 5 passi

1. Clona e riparti da zero con git:
   ```bash
   git clone <questo-repo> nome-cliente && cd nome-cliente && rm -rf .git && git init
   ```
2. Brand: in `config/settings.py` imposta `THEME` (`brand`, `mark`, `company`, `company_url`, `version`, `nav`).
3. Palette (opzionale): cambia i valori in `theme/static/theme/tokens.css`.
   Verifica il contrasto del primario su bianco (minimo AA 4,5:1).
   Aggiorna anche il colore fisso della favicon in `theme/views.py`.
4. L'app `core` è un esempio (modello `Cliente`, home, `/stile/`, `/profilo/`):
   svuotala, rinominala o usala come base.
5. Ambiente:
   ```bash
   python3 -m venv .venv && . .venv/bin/activate
   pip install -r requirements-dev.txt
   cp .env.example .env            # imposta SECRET_KEY
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py runserver
   ```
   Apri `http://127.0.0.1:8000/stile/` (catalogo dei componenti) e `/admin/`.

## Struttura

- `config/` settings unico via `.env`, urls, wsgi.
- `theme/` tutta la grafica: template admin, shell frontend (`theme/base.html`),
  login/lockout/errori, `tokens.css` (colori), `admin.css`, `ui.css`, `ui.js`,
  favicon dinamica con la sigla. **Non importa nulla da `core` o `config`**:
  si può copiare in un altro progetto così com'è (test `test_portabilita.py`).
- `core/` app di esempio.

## Usare il tema nelle tue pagine

```django
{% extends 'theme/base.html' %}
{% block title %}Titolo · {{ theme.brand }}{% endblock %}
{% block content %}
  <div class="ui-pagehead"><div><h1>Titolo</h1><div class="sub">Sottotitolo</div></div></div>
  <div class="ui-card is-revealed"><div class="ui-card-body">…</div></div>
{% endblock %}
```

Tutti i componenti, con lo snippet da copiare, sono in `/stile/`.

## Sicurezza inclusa

- django-axes: 5 tentativi, blocco 15 min per username+IP (`AXES_*` in `.env`).
- Sessione 30 min rinnovata a ogni richiesta, cookie HttpOnly, `X-Frame-Options: DENY`.
- Con `DEBUG=False`: cookie Secure, `X-Forwarded-Proto` dal proxy, log su file in
  `logs/`, mail agli `ADMINS` sugli errori 500. HSTS spento finché non lo accendi
  tu con `SECURE_HSTS_SECONDS`.

## Test

```bash
pytest
```

## Fuori scope (deliberatamente)

Docker, deploy, CI, reset password via mail, dark mode, lingue oltre l'italiano.
````

- [ ] **Step 2: test completi e check di deploy**

Run:
```bash
pytest -q
DEBUG=False SECRET_KEY=$(python -c "from django.core.management.utils import get_random_secret_key as k; print(k())") ALLOWED_HOSTS=localhost python manage.py check --deploy
```
Expected: tutti i test passano; `check --deploy` segnala solo i warning HSTS (`security.W004`) e `W008` (SSL redirect). Qualunque altro warning va risolto nei settings.

- [ ] **Step 3: verifica nel browser**

```bash
cp .env.example .env && sed -i 's/^SECRET_KEY=.*/SECRET_KEY=dev-solo-locale/' .env
python manage.py migrate
DJANGO_SUPERUSER_PASSWORD='Admin12345!' python manage.py createsuperuser --noinput --username admin --email admin@example.com
python manage.py runserver 8000
```

Con un browser (o lo skill `run` se disponibile) controlla, prendendo uno screenshot per ciascuna:

1. `/accounts/login/` — card centrata, badge "PR", mostra/nascondi password funziona, credenziali errate → alert rosso.
2. `/` da loggato — header con blur, nav "Home/Stile" con sottolineatura attiva, dropdown profilo apre/chiude al click e con Esc, 3 KPI, empty state.
3. `/admin/` — header 60px con badge, dashboard a due colonne, `Clienti` → aggiungi un cliente → changelist con filtri a destra in card, pulsanti pill.
4. `/` di nuovo — tabella con la riga appena creata, animazione d'ingresso.
5. `/stile/` — ogni sezione renderizzata e snippet sotto; i due toast compaiono e spariscono.
6. Finestra a 375px di larghezza — hamburger apre la nav verticale, niente scroll orizzontale.
7. `/pagina-inesistente/` — scheda 404 in stile.

Se qualcosa è rotto nel CSS: è quasi sempre una regola persa o un selettore non rinominato nel Task 3; correggi `ui.css` e ri-esegui `pytest theme/tests/test_css.py`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: README con procedura per un nuovo cliente

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review (fatta in scrittura)

- **Copertura spec:** struttura (T1), token/admin/favicon (T2), ui.css (T3), ui.js/icone (T4), base/header/footer con nav da settings (T5), login/password/lockout/errori (T6), portabilità + settings produzione (T7), core modello/home (T8), stile/profilo (T9), axes (T10), README e verifica (T11). Scostamenti dalla spec dichiarati in testa: favicon dinamica, `403_csrf.html`.
- **Coerenza nomi:** `theme:favicon` (T2, T5, T6), `core:home/stile/profilo` (T1, T8, T9), classi `ui-*` identiche fra `test_css.py` (T3), template (T5-T9) e catalogo (T9); `uiToast` (T4, T9); `cooloff_timedelta` nel lockout (T6, T10).
- **Rischi noti:** gli intervalli di riga di `siee.css` valgono per la versione a 2096 righe; il piano dice come riallinearli. La regex dello sprite icone presuppone `<symbol>`; il piano dice cosa fare altrimenti.
