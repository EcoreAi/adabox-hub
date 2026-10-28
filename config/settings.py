"""
Settings unico: sviluppo e produzione differiscono solo per DEBUG e per le
variabili in .env (vedi .env.example).
"""
import sys
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")

from core import __version__ as CORE_VERSION  # noqa: E402  core/__init__.py non importa Django
from core.registry import bootstrap  # noqa: E402

# --- Moduli (addons) -----------------------------------------------------
# Lo stato di installazione sta in ADDONS_DIR/installed.json; ADDONS_FORCE
# aggiunge moduli presenti su disco (lo usa pytest, vedi pytest.ini).
ADDONS_DIR = Path(env("ADDONS_DIR", default=str(BASE_DIR / "addons")))
if str(ADDONS_DIR) not in sys.path:
    sys.path.insert(0, str(ADDONS_DIR))
ADDONS_ATTIVI = bootstrap.moduli_installati(ADDONS_DIR, forzati=env.list("ADDONS_FORCE", default=[]))

SECRET_KEY = env("SECRET_KEY", default="solo-sviluppo-cambiami")
# chiave Fernet per i segreti salvati nel database (chiavi API...): senza, derivata da SECRET_KEY
CHIAVE_CIFRATURA = env("CHIAVE_CIFRATURA", default="")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# Brand: letto dal context processor theme.context_processors.theme
THEME = {
    "brand": "Adabox Hub",
    "mark": "AH",
    "company": "ICHNOBYTE S.R.L.",
    "company_url": "https://ichnobyte.it/",
    "version": "0.1.0",
    "nav": [],  # la riempie core.context_processors.piattaforma con le app installate
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
    "ninja",
    "core",
    *ADDONS_ATTIVI,
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.AziendaCorrenteMiddleware",
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
                "core.context_processors.piattaforma",
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
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Backup prima di installare/aggiornare/disinstallare un modulo
BACKUP_DIR = Path(env("BACKUP_DIR", default=str(BASE_DIR / "backup")))
BACKUP_CONSERVA = env.int("BACKUP_CONSERVA", default=10)
# Ricarica del server dopo un cambio di moduli: gunicorn (SIGHUP via pidfile), runserver o none
RELOAD_STRATEGY = env("RELOAD_STRATEGY", default="runserver" if DEBUG else "gunicorn")
GUNICORN_PIDFILE = env("GUNICORN_PIDFILE", default="/tmp/gunicorn.pid")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Servizi del kernel (fase 2) -----------------------------------------
# Lavori in background: con True `accoda` esegue subito, nello stesso processo
# (sviluppo e test); in produzione False e `manage.py worker` in un container.
LAVORI_SINCRONI = env.bool("LAVORI_SINCRONI", default=DEBUG)
# File privati (allegati): mai serviti direttamente, solo dalla vista con i permessi
PRIVATE_MEDIA_ROOT = Path(env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private")))
ALLEGATI_MAX_MB = env.int("ALLEGATI_MAX_MB", default=20)
# Con nginx davanti: il download passa a nginx (location internal /_privati/)
ALLEGATI_X_ACCEL = env.bool("ALLEGATI_X_ACCEL", default=False)
# Indirizzo base assoluto per i link nelle email (es. https://hub.cliente.it)
SITO_URL = env("SITO_URL", default="http://localhost:8000").rstrip("/")
# app mostrate nella barra in alto (oltre alla Dashboard); le altre vanno nel menu "Altre"
NAV_APP_VISIBILI = env.int("NAV_APP_VISIBILI", default=4)
# Posta in entrata del chatter: casella delle risposte (con indirizzi +token) e accesso IMAP
EMAIL_RISPOSTE = env("EMAIL_RISPOSTE", default="")
IMAP_URL = env("IMAP_URL", default="")
# Export e import oltre queste righe passano dal worker
EXPORT_SINCRONO_MAX = env.int("EXPORT_SINCRONO_MAX", default=5000)
IMPORT_SINCRONO_MAX = env.int("IMPORT_SINCRONO_MAX", default=1000)
# Stampe PDF di massa oltre questi record passano dal worker
REPORT_SINCRONO_MAX = env.int("REPORT_SINCRONO_MAX", default=20)

# --- Distribuzione dei moduli (fase 4) -------------------------------------
# Chiavi pubbliche Ed25519 (base64, separate da virgola) di cui l'istanza si fida per i pacchetti
MODULI_CHIAVI_FIDATE = env.list("MODULI_CHIAVI_FIDATE", default=[])
# In produzione si caricano solo pacchetti firmati da una chiave fidata
MODULI_FIRMA_OBBLIGATORIA = env.bool("MODULI_FIRMA_OBBLIGATORIA", default=not DEBUG)
MODULI_ZIP_MAX_MB = env.int("MODULI_ZIP_MAX_MB", default=20)
# Catalogo dei moduli approvati: URL (https://… o file://…) di indice.json, con indice.sig accanto
MODULI_CATALOGO_URL = env("MODULI_CATALOGO_URL", default="")

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
    # IP del client per axes (serve django-ipware, vedi requirements.txt).
    # nginx con "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;"
    # aggiunge in coda l'IP reale: ipware conta come proxy solo le voci di
    # X-Forwarded-For dopo il client, quindi 0 = prendi l'ultima voce.
    # IPWARE_STRICT=False: con voci in piu' scritte dal client (falsificabili)
    # l'header resta valido e vince comunque l'ultima, invece di ricadere su
    # REMOTE_ADDR (127.0.0.1, uguale per tutti).
    AXES_IPWARE_PROXY_COUNT = 0
    AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]
    IPWARE_STRICT = False

# --- Mail di errore e logging -------------------------------------------
ADMINS = [tuple(p.split(":", 1)) for p in env.list("ADMINS", default=[]) if ":" in p]
# SMTP da EMAIL_URL (es. smtp+tls://utente:password@smtp.example.com:587);
# senza, le mail finiscono sulla console.
EMAIL_CONFIG = env.email_url("EMAIL_URL", default="consolemail://")
EMAIL_BACKEND = EMAIL_CONFIG["EMAIL_BACKEND"]
EMAIL_HOST = EMAIL_CONFIG.get("EMAIL_HOST", "localhost")
EMAIL_PORT = EMAIL_CONFIG.get("EMAIL_PORT", 25)
EMAIL_HOST_USER = EMAIL_CONFIG.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = EMAIL_CONFIG.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = EMAIL_CONFIG.get("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = EMAIL_CONFIG.get("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@localhost")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
_file_handlers = {}
_file_handler_names = []
if not DEBUG:
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
    "filters": {"require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "std"},
        "mail_admins": {"class": "django.utils.log.AdminEmailHandler", "level": "ERROR",
                        "filters": ["require_debug_false"]},
        # Storico di installazioni e aggiornamenti dei moduli: sempre, anche in sviluppo
        "file_moduli": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "moduli.log",
            "maxBytes": 5 * 1024 * 1024, "backupCount": 5,
            "level": "INFO", "formatter": "std",
        },
        **_file_handlers,
    },
    "root": {"handlers": ["console", *_file_handler_names], "level": "INFO"},
    "loggers": {
        "django.request": {
            "handlers": ["console", "mail_admins", *_file_handler_names],
            "level": "ERROR", "propagate": False,
        },
        "core.moduli": {"handlers": ["file_moduli"], "level": "INFO", "propagate": True},
        # WeasyPrint e fontTools scrivono centinaia di righe INFO per ogni PDF
        "weasyprint": {"level": "WARNING"},
        "fontTools": {"level": "WARNING"},
    },
}
