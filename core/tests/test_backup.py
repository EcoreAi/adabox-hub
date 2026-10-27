import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from core import backup


@pytest.fixture
def cartella(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path / "backup"
    return settings.BACKUP_DIR


@pytest.mark.django_db
@pytest.mark.skipif("sqlite" not in __import__("django.conf").conf.settings.DATABASES["default"]["ENGINE"],
                    reason="backup sqlite")
def test_backup_sqlite(cartella):
    dest = backup.esegui("prova")
    assert dest.parent == cartella and dest.name.endswith("-prova.sqlite3")
    con = sqlite3.connect(dest)
    tabelle = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    con.close()
    assert "core_azienda" in tabelle


def _postgres(settings, monkeypatch, returncode=0, stderr=""):
    db = {**settings.DATABASES["default"], "ENGINE": "django.db.backends.postgresql", "HOST": "db",
          "PORT": "5433", "USER": "hub", "NAME": "hubdb", "PASSWORD": "segreta"}
    monkeypatch.setitem(settings.DATABASES, "default", db)
    chiamate = []

    def finto_run(cmd, **kw):
        chiamate.append((cmd, kw))
        return SimpleNamespace(returncode=returncode, stderr=stderr, stdout="")
    monkeypatch.setattr(subprocess, "run", finto_run)
    return chiamate


def test_backup_postgres(settings, monkeypatch, cartella):
    chiamate = _postgres(settings, monkeypatch)
    dest = backup.esegui("prova")
    ((cmd, kw),) = chiamate
    assert cmd[0] == "pg_dump" and "-Fc" in cmd
    assert cmd[cmd.index("--dbname") + 1] == "postgresql://hub@db:5433/hubdb"
    assert kw["env"]["PGPASSWORD"] == "segreta"
    assert cmd[cmd.index("--file") + 1] == str(dest) and dest.parent == cartella


def test_backup_postgres_fallito(settings, monkeypatch, cartella):
    _postgres(settings, monkeypatch, returncode=1, stderr="connessione rifiutata")
    with pytest.raises(backup.BackupFallito) as exc:
        backup.esegui("prova")
    assert "connessione rifiutata" in str(exc.value)


def test_pulisci_tiene_gli_ultimi(settings, cartella):
    settings.BACKUP_CONSERVA = 3
    cartella.mkdir()
    for i in range(6):
        (cartella / f"2026-10-0{i + 1}-120000-x.sqlite3").write_text("")
    backup.pulisci()
    assert sorted(p.name[:10] for p in cartella.iterdir()) == ["2026-10-04", "2026-10-05", "2026-10-06"]


def test_engine_sconosciuto(settings, monkeypatch, cartella):
    monkeypatch.setitem(settings.DATABASES, "default", {**settings.DATABASES["default"], "ENGINE": "x.oracle"})
    with pytest.raises(backup.BackupFallito):
        backup.esegui("prova")
