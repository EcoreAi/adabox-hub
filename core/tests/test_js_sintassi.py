"""Un errore di sintassi in uno script ferma tutta la pagina e nessun test Python se ne accorge: li controlla node."""
import shutil
import subprocess
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parents[2]
SCRIPT = sorted(p for cartella in ("core", "addons", "theme") for p in (RADICE / cartella).glob("**/static/**/*.js")
                if "vendor" not in p.parts and not p.name.endswith(".min.js"))


@pytest.mark.skipif(shutil.which("node") is None, reason="node non installato")
@pytest.mark.parametrize("script", SCRIPT, ids=lambda p: str(p.relative_to(RADICE)))
def test_sintassi(script):
    esito = subprocess.run(["node", "--check", str(script)], capture_output=True, text=True, timeout=30)
    assert esito.returncode == 0, esito.stderr[-1500:]
