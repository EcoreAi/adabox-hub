"""Installazione vergine end-to-end: DB vuoto, modulo installa, disinstalla --elimina-dati."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

BASE_DIR = Path(settings.BASE_DIR)


@pytest.mark.slow
def test_installazione_vergine(tmp_path):
    addons = tmp_path / "addons"
    addons.mkdir()
    shutil.copytree(BASE_DIR / "addons" / "todo", addons / "todo", ignore=shutil.ignore_patterns("__pycache__"))
    env = {**os.environ, "ADDONS_DIR": str(addons), "DATABASE_URL": f"sqlite:///{tmp_path / 'db.sqlite3'}",
           "BACKUP_DIR": str(tmp_path / "backup"), "RELOAD_STRATEGY": "none", "DEBUG": "True"}
    env.pop("ADDONS_FORCE", None)

    def run(*args):
        esito = subprocess.run([sys.executable, "manage.py", *args], cwd=BASE_DIR, env=env,
                               capture_output=True, text=True)
        assert esito.returncode == 0, esito.stdout + esito.stderr
        return esito.stdout

    run("migrate", "--noinput")
    run("shell", "--no-imports", "-c", "from django.contrib.auth.models import User; User.objects.create_user('lucia', '', 'x')")
    assert "== FINE ok ==" in run("modulo", "installa", "todo", "--demo", "--si")
    assert "todo" in json.loads((addons / "installed.json").read_text())["installed"]
    assert "installato" in run("modulo", "lista")
    conta = run("shell", "--no-imports", "-c", "from todo.models import Attivita; print(Attivita.objects.count())")
    assert conta.strip() == "10"
    gruppi = run("shell", "--no-imports", "-c", "from django.contrib.auth.models import User; "
                                "print(list(User.objects.get(username='lucia').groups.values_list('name', flat=True)))")
    assert "To-Do / Utente" in gruppi
    assert list((tmp_path / "backup").glob("*-pre-installa-todo.sqlite3"))
    run("modulo", "disinstalla", "todo", "--elimina-dati", "--si")
    assert json.loads((addons / "installed.json").read_text())["installed"] == []
    tabelle = run("shell", "--no-imports", "-c", "from django.db import connection; print(connection.introspection.table_names())")
    assert "todo_attivita" not in tabelle
    assert "To-Do / Utente" not in run("shell", "--no-imports", "-c", "from django.contrib.auth.models import Group; "
                                                     "print(list(Group.objects.values_list('name', flat=True)))")
