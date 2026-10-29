"""Collaudo di un modulo: installazione vergine con le dipendenze in un'istanza usa e getta, test, disinstallazione."""
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings

from . import modules

TIMEOUT_PASSO = 900


@dataclass
class Risultato:
    slug: str
    ok: bool
    passi: list = field(default_factory=list)          # [(nome del passo, ok)]
    dettaglio: str = ""                                # coda dell'output del passo fallito


def da_collaudare(slugs=None):
    """Gli slug in ordine di dipendenze (tutti quelli con manifest valido se `slugs` è vuoto)."""
    info = {s: i for s, i in modules.scopri().items() if i.manifest is not None}
    scelti = list(slugs) if slugs else list(info)
    mancanti = [s for s in scelti if s not in info]
    if mancanti:
        raise ValueError(f"moduli non trovati o con manifest non valido: {', '.join(mancanti)}")
    return modules.ordina(scelti, info), info


def _chiusura(slug, info):
    visti, da_vedere = [], [slug]
    while da_vedere:
        s = da_vedere.pop()
        if s not in visti:
            visti.append(s)
            da_vedere.extend(modules.dipendenze(s, info))
    return visti


def collauda(slug, info):
    """Istanza temporanea con `slug` e le sue dipendenze: migrate, installa --demo, test del modulo,
    disinstalla --elimina-dati. Ogni passo è un processo nuovo, come in produzione."""
    risultato = Risultato(slug=slug, ok=True)
    base = Path(settings.BASE_DIR)
    with tempfile.TemporaryDirectory(prefix=f"collaudo-{slug}-") as tmp:
        tmp = Path(tmp)
        addons = tmp / "addons"
        moduli = _chiusura(slug, info)
        for s in moduli:
            shutil.copytree(info[s].cartella, addons / s, ignore=shutil.ignore_patterns("__pycache__", ".adabox-origine.json"))
        env = {**os.environ, "ADDONS_DIR": str(addons), "DATABASE_URL": f"sqlite:///{tmp / 'db.sqlite3'}",
               "BACKUP_DIR": str(tmp / "backup"), "RELOAD_STRATEGY": "none", "DEBUG": "True",
               "LAVORI_SINCRONI": "True", "AI_TURNI_SINCRONI": "True", "PRIVATE_MEDIA_ROOT": str(tmp / "private")}
        env.pop("ADDONS_FORCE", None)
        manage = [sys.executable, str(base / "manage.py")]
        passi = [("migrate", manage + ["migrate", "--noinput"], env),
                 ("installa", manage + ["modulo", "installa", slug, "--demo", "--si"], env)]
        test = addons / slug / "tests"
        if test.is_dir():
            # i test girano su un DB di test proprio, con le fixture condivise del progetto (conftest.py copiato
            # alla radice dell'istanza) e ADDONS_FORCE che carica il modulo e le sue dipendenze
            shutil.copy(base / "conftest.py", addons / "conftest.py")
            passi.append(("test", [sys.executable, "-m", "pytest", str(test), "-q", "-m", "not slow",
                                   "-c", str(base / "pytest.ini"), "--rootdir", str(addons), "-p", "no:cacheprovider",
                                   "-o", f"env=ADDONS_FORCE={','.join(reversed(moduli))}"], env))
        passi.append(("disinstalla", manage + ["modulo", "disinstalla", slug, "--elimina-dati", "--si"], env))
        for nome, comando, ambiente in passi:
            try:
                esito = subprocess.run(comando, cwd=base, env=ambiente, capture_output=True, text=True,
                                       timeout=TIMEOUT_PASSO)
                riuscito, uscita = esito.returncode == 0, esito.stdout + esito.stderr
            except subprocess.TimeoutExpired:
                riuscito, uscita = False, f"tempo scaduto ({TIMEOUT_PASSO} s)"
            risultato.passi.append((nome, riuscito))
            if not riuscito:
                risultato.ok, risultato.dettaglio = False, uscita[-3000:]
                break
    return risultato
