"""End-to-end nel sottoprocesso: installazione vergine, disinstallazione, aggiornamento 1.0.0 -> 1.1.0."""
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from django.conf import settings

BASE_DIR = Path(settings.BASE_DIR)
COMMIT_1_0 = "bac7e7c"          # todo 1.0.0, fine della fase 1


def _ambiente(tmp_path):
    """Cartella addons vuota, DB sqlite nuovo e un `run(*args)` di manage.py su quell'istanza."""
    addons = tmp_path / "addons"
    addons.mkdir()
    env = {**os.environ, "ADDONS_DIR": str(addons), "DATABASE_URL": f"sqlite:///{tmp_path / 'db.sqlite3'}",
           "BACKUP_DIR": str(tmp_path / "backup"), "RELOAD_STRATEGY": "none", "DEBUG": "True",
           "LAVORI_SINCRONI": "True", "PRIVATE_MEDIA_ROOT": str(tmp_path / "private")}
    env.pop("ADDONS_FORCE", None)

    def run(*args):
        esito = subprocess.run([sys.executable, "manage.py", *args], cwd=BASE_DIR, env=env,
                               capture_output=True, text=True)
        assert esito.returncode == 0, esito.stdout + esito.stderr
        return esito.stdout

    def shell(codice):
        return run("shell", "--no-imports", "-c", codice)
    return addons, run, shell


def _copia_attuale(addons):
    shutil.copytree(BASE_DIR / "addons" / "todo", addons / "todo", ignore=shutil.ignore_patterns("__pycache__"))


@pytest.mark.slow
def test_installazione_vergine(tmp_path):
    addons, run, shell = _ambiente(tmp_path)
    _copia_attuale(addons)
    run("migrate", "--noinput")
    shell("from django.contrib.auth.models import User; User.objects.create_user('lucia', '', 'x')")
    assert "== FINE ok ==" in run("modulo", "installa", "todo", "--demo", "--si")
    assert "todo" in json.loads((addons / "installed.json").read_text())["installed"]
    assert "installato" in run("modulo", "lista")
    assert shell("from todo.models import Attivita; print(Attivita.objects.count())").strip() == "10"
    assert shell("from todo.models import Attivita; print(Attivita.objects.filter(numero='').count())").strip() == "0"
    gruppi = shell("from django.contrib.auth.models import User; "
                   "print(list(User.objects.get(username='lucia').groups.values_list('name', flat=True)))")
    assert "To-Do / Utente" in gruppi
    assert "Promemoria scadenze" in shell("from core.models import Pianificazione; "
                                          "print(list(Pianificazione.objects.values_list('nome', flat=True)))")
    assert list((tmp_path / "backup").glob("*-pre-installa-todo.sqlite3"))
    run("modulo", "disinstalla", "todo", "--elimina-dati", "--si")
    assert json.loads((addons / "installed.json").read_text())["installed"] == []
    tabelle = shell("from django.db import connection; print(connection.introspection.table_names())")
    assert "todo_attivita" not in tabelle
    assert "To-Do / Utente" not in shell("from django.contrib.auth.models import Group; "
                                         "print(list(Group.objects.values_list('name', flat=True)))")
    resto = shell("from core.models import Pianificazione, Sequenza; "
                  "print(Pianificazione.objects.filter(modulo='todo').count(), "
                  "Sequenza.objects.filter(codice__startswith='todo.').count())")
    assert resto.split() == ["0", "0"]


@pytest.mark.slow
def test_aggiornamento_da_1_0(tmp_path):
    addons, run, shell = _ambiente(tmp_path)
    archivio = subprocess.run(["git", "archive", COMMIT_1_0, "addons/todo"], cwd=BASE_DIR,
                              capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archivio)) as tar:
        tar.extractall(tmp_path / "v1_0", filter="data")
    shutil.copytree(tmp_path / "v1_0" / "addons" / "todo", addons / "todo")
    run("migrate", "--noinput")
    run("modulo", "installa", "todo", "--demo", "--si")
    assert "1.0.0" in run("modulo", "lista")

    shutil.rmtree(addons / "todo")
    _copia_attuale(addons)
    assert "da_aggiornare" in run("modulo", "lista")
    assert "== FINE ok ==" in run("modulo", "aggiorna", "todo")
    lista = run("modulo", "lista")
    assert "1.1.0" in lista and "installato" in lista
    numeri = shell("from todo.models import Attivita; print(list(Attivita.objects.values_list('numero', flat=True)))")
    assert numeri.count("ATT/") == 10
    assert "Promemoria scadenze" in shell("from core.models import Pianificazione; "
                                          "print(list(Pianificazione.objects.values_list('nome', flat=True)))")
