import os
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SETTINGS = Path(__file__).resolve().parents[1] / "settings.py"


def _carica(debug, **extra):
    """Esegue settings.py in un namespace nuovo (niente reload: gli
    attributi di un caricamento precedente non devono sopravvivere).
    Non tocca django.conf.settings; os.environ viene ripristinato."""
    env = {"DEBUG": debug, "SECRET_KEY": "x", "SECURE_HSTS_SECONDS": "0", **extra}
    with mock.patch.dict(os.environ, env, clear=False):
        if "EMAIL_URL" not in extra:
            os.environ.pop("EMAIL_URL", None)
        return SimpleNamespace(**runpy.run_path(str(SETTINGS)))


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


def test_mail_di_default_su_console():
    s = _carica("False")
    assert s.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend"


def test_mail_smtp_da_email_url():
    s = _carica("False", EMAIL_URL="smtp+tls://u:p@smtp.example.com:587")
    assert s.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
    assert s.EMAIL_HOST == "smtp.example.com"
    assert s.EMAIL_PORT == 587
    assert s.EMAIL_HOST_USER == "u"
    assert s.EMAIL_HOST_PASSWORD == "p"
    assert s.EMAIL_USE_TLS is True


def test_mail_admins_solo_con_debug_false():
    s = _carica("True")
    assert "require_debug_false" in s.LOGGING["filters"]
    assert s.LOGGING["filters"]["require_debug_false"]["()"] == "django.utils.log.RequireDebugFalse"
    assert s.LOGGING["handlers"]["mail_admins"]["filters"] == ["require_debug_false"]


def test_addons_installati_in_installed_apps(tmp_path):
    import json
    import sys
    (tmp_path / "alfa").mkdir()
    (tmp_path / "alfa" / "__manifest__.py").write_text("{'name': 'Alfa', 'version': '1.0.0', 'min_core': '1.0'}")
    (tmp_path / "installed.json").write_text(json.dumps({"schema": 1, "installed": ["alfa"]}))
    percorso = sys.path[:]
    try:
        s = _carica("True", ADDONS_DIR=str(tmp_path), ADDONS_FORCE="")
        assert "alfa" in s.INSTALLED_APPS
        assert s.ADDONS_ATTIVI == ["alfa"]
        assert str(tmp_path) in sys.path
    finally:
        sys.path[:] = percorso
