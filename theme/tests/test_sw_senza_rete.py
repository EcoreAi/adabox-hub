"""Il service worker (theme/templates/theme/sw.js) eseguito davvero, senza browser: `sw_simulato.js` gli simula le cache,
la rete, l'orologio e il browser che segue i reindirizzamenti. Serve Node: dove non c'è, la prova si salta."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from theme import views

SIMULATORE = Path(__file__).with_name("sw_simulato.js")
SENZA_RETE = {"pagine": ["/iem/scansiona/"], "statici": ["/static/iem/scansiona.js?v=7", "/static/iem/manca.js?v=1"]}


@pytest.mark.skipif(shutil.which("node") is None, reason="serve Node per eseguire il service worker")
def test_le_pagine_senza_rete_nel_service_worker(tmp_path):
    """La copia quando la rete manca o tarda, l'avvio dell'app e le scorciatoie che portano alla copia, ciò che non si
    salva, la pulizia al cambio di persona: gli scenari sono in sw_simulato.js, uno per riga dell'esito."""
    sw = tmp_path / "sw.js"
    sw.write_text(render_to_string("theme/sw.js", {"senza_rete": json.dumps(SENZA_RETE), "cache_pagine": views.CACHE_PAGINE}), encoding="utf-8")
    esito = subprocess.run(["node", str(SIMULATORE), str(sw)], capture_output=True, text=True, timeout=120)
    assert esito.returncode == 0, esito.stdout + esito.stderr


def test_la_pagina_offline_elenca_le_copie_dalla_cache_del_service_worker(client):
    """«Sei offline» legge la stessa cache in cui il service worker tiene le copie, e salta i suoi appunti."""
    pagina = client.get("/offline/").content.decode()
    codice = client.get("/sw.js").content.decode()
    assert f"cache = '{views.CACHE_PAGINE}'" in pagina and f"const PAGINE = '{views.CACHE_PAGINE}';" in codice
    assert "const RICORDI = '/sw-porta-a/';" in codice and "percorso === '/sw-porta-a/'" in pagina
    assert 'id="salvate" hidden' in pagina and "{{" not in pagina and "{{" not in codice
