"""Pagina Moduli: lancia `manage.py modulo` in un sottoprocesso e ne mostra il log."""
import os
import re
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.utils import timezone

LOG_RE = re.compile(r"^moduli-[a-z0-9_]+-\d{8}-\d{6}\.log$")
FINE_RE = re.compile(r"^== FINE (ok|errore) ==$", re.M)
RIGHE_CODA = 60


def comando(op, slug, demo=False, elimina_dati=False):
    cmd = [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "modulo", op, slug]
    if op in ("installa", "disinstalla"):
        cmd.append("--si")
    cmd.append("--riavvia")
    if op == "installa" and demo:
        cmd.append("--demo")
    if op == "disinstalla" and elimina_dati:
        cmd.append("--elimina-dati")
    return cmd


def avvia(op, slug, **opzioni):
    """Avvia il comando staccato dal processo web (sopravvive alla ricarica). Restituisce il nome del log."""
    cartella = Path(settings.LOG_DIR)
    cartella.mkdir(parents=True, exist_ok=True)
    nome = f"moduli-{slug}-{timezone.localtime().strftime('%Y%m%d-%H%M%S')}.log"
    env = {**os.environ, "ADDONS_DIR": str(settings.ADDONS_DIR), "PYTHONUNBUFFERED": "1"}
    with open(cartella / nome, "w") as log:
        subprocess.Popen(comando(op, slug, **opzioni), stdout=log, stderr=subprocess.STDOUT,
                         cwd=settings.BASE_DIR, env=env, start_new_session=True)
    return nome


def leggi(nome):
    """(coda del log, stato) con stato 'in_corso', 'completato' o 'fallito'. ValueError se il nome non è valido."""
    if not LOG_RE.match(nome or ""):
        raise ValueError(nome)
    percorso = Path(settings.LOG_DIR) / nome
    testo = percorso.read_text(errors="replace") if percorso.exists() else ""
    coda = "\n".join(testo.splitlines()[-RIGHE_CODA:])
    fine = FINE_RE.search(testo)
    stato = "in_corso" if not fine else "completato" if fine.group(1) == "ok" else "fallito"
    return coda, stato
