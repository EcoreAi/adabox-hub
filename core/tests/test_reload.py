import os
import signal
from pathlib import Path

import pytest

from core.registry import reload


@pytest.fixture
def chiamate(monkeypatch):
    registro = []
    monkeypatch.setattr(os, "kill", lambda *a: registro.append(("kill", a)))
    monkeypatch.setattr(os, "utime", lambda *a: registro.append(("utime", a)))
    return registro


def test_none(settings, chiamate):
    settings.RELOAD_STRATEGY = "none"
    assert reload.richiedi() is False and chiamate == []


def test_gunicorn(settings, chiamate, tmp_path):
    settings.RELOAD_STRATEGY = "gunicorn"
    settings.GUNICORN_PIDFILE = tmp_path / "g.pid"
    (tmp_path / "g.pid").write_text("4242\n")
    assert reload.richiedi() is True
    assert chiamate == [("kill", (4242, signal.SIGHUP))]


def test_gunicorn_senza_pidfile(settings, chiamate, tmp_path):
    settings.RELOAD_STRATEGY = "gunicorn"
    settings.GUNICORN_PIDFILE = tmp_path / "assente.pid"
    with pytest.raises(reload.RicaricaNonDisponibile):
        reload.richiedi()


def test_runserver(settings, chiamate):
    settings.RELOAD_STRATEGY = "runserver"
    assert reload.richiedi() is True
    ((tipo, (percorso,)),) = chiamate
    assert tipo == "utime" and Path(percorso) == Path(settings.BASE_DIR) / "config" / "settings.py"


def test_sconosciuta(settings):
    settings.RELOAD_STRATEGY = "boh"
    with pytest.raises(ValueError):
        reload.richiedi()
