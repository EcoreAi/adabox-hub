"""End-to-end: installazione vergine di tutte le app della fase 3 con le dipendenze, poi disinstallazione."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.conf import settings

BASE_DIR = Path(settings.BASE_DIR)
APP = ["contatti", "calendario", "crm", "helpdesk", "progetti", "timesheet"]


@pytest.mark.slow
def test_tutte_le_app(tmp_path):
    addons = tmp_path / "addons"
    addons.mkdir()
    for app in APP:
        shutil.copytree(BASE_DIR / "addons" / app, addons / app, ignore=shutil.ignore_patterns("__pycache__"))
    env = {**os.environ, "ADDONS_DIR": str(addons), "DATABASE_URL": f"sqlite:///{tmp_path / 'db.sqlite3'}",
           "BACKUP_DIR": str(tmp_path / "backup"), "RELOAD_STRATEGY": "none", "DEBUG": "True",
           "LAVORI_SINCRONI": "True", "PRIVATE_MEDIA_ROOT": str(tmp_path / "private")}
    env.pop("ADDONS_FORCE", None)

    def run(*args, ok=True):
        esito = subprocess.run([sys.executable, "manage.py", *args], cwd=BASE_DIR, env=env, capture_output=True, text=True)
        if ok:
            assert esito.returncode == 0, esito.stdout + esito.stderr
        return esito

    def shell(codice):
        return run("shell", "--no-imports", "-c", codice).stdout.strip()

    run("migrate", "--noinput")
    shell("from django.contrib.auth.models import User; User.objects.create_user('ugo', 'ugo@example.com', 'x')")
    uscita = run("modulo", "installa", "timesheet", "crm", "helpdesk", "calendario", "--demo", "--si").stdout
    assert "Verranno installate anche le dipendenze: contatti, progetti" in uscita and "== FINE ok ==" in uscita

    installati = json.loads((addons / "installed.json").read_text())["installed"]
    assert set(installati) == set(APP)
    assert installati.index("contatti") < min(installati.index(a) for a in ("crm", "helpdesk", "calendario", "progetti"))
    assert installati.index("progetti") < installati.index("timesheet")

    conteggi = shell("from contatti.models import Contatto; from crm.models import Opportunita; "
                     "from helpdesk.models import Ticket; from calendario.models import Evento; "
                     "from progetti.models import Progetto, Compito; "
                     "print(Contatto.objects.exclude(codice='').count(), Opportunita.objects.count(), "
                     "Ticket.objects.exclude(numero='').exclude(scadenza_sla=None).count(), Evento.objects.count(), "
                     "Progetto.objects.exclude(codice='').count(), Compito.objects.count())")
    assert conteggi.split() == ["6", "6", "5", "4", "2", "6"]
    gruppi = shell("from django.contrib.auth.models import User; "
                   "print(sorted(User.objects.get(username='ugo').groups.values_list('name', flat=True)))")
    for gruppo in ("Contatti / Utente", "CRM / Commerciale", "Helpdesk / Operatore", "Calendario / Utente",
                   "Progetti / Utente", "Timesheet / Utente"):
        assert gruppo in gruppi
    assert "Avvisi SLA" in shell("from core.models import Pianificazione; "
                                 "print(list(Pianificazione.objects.values_list('nome', flat=True)))")

    rifiuto = run("modulo", "disinstalla", "progetti", "--si", ok=False)
    assert rifiuto.returncode != 0 and "timesheet" in rifiuto.stderr + rifiuto.stdout

    for app in ("timesheet", "progetti", "helpdesk", "crm", "calendario", "contatti"):
        run("modulo", "disinstalla", app, "--elimina-dati", "--si")
    assert json.loads((addons / "installed.json").read_text())["installed"] == []
    tabelle = shell("from django.db import connection; print(connection.introspection.table_names())")
    for tabella in ("contatti_contatto", "crm_opportunita", "helpdesk_ticket", "progetti_compito", "timesheet_rigaore"):
        assert tabella not in tabelle
