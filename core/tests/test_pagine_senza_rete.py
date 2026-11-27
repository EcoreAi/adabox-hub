"""Le pagine che un modulo dichiara apribili senza rete (hooks.pagina_senza_rete): il service worker dell'app
installata riceve l'elenco delle pagine e dei loro file. Che cosa ne fa nel browser non si prova qui."""
import json
import re

import pytest
from django.urls import reverse

from core.registry import hooks, modules

pytestmark = pytest.mark.django_db


def _elenco(client):
    codice = client.get("/sw.js").content.decode()
    return json.loads(re.search(r"const SENZA_RETE = (\{.*?\});", codice).group(1)), codice


@pytest.fixture
def scanner(monkeypatch):
    monkeypatch.setattr(hooks, "_senza_rete", [])
    pagina = modules.manifests_attivi()["crm"].menu[0]["url_name"]
    hooks.pagina_senza_rete(pagina, statici=["core/push.js", "core/push.js"])
    hooks.pagina_senza_rete(pagina)                              # registrata due volte (ready() rieseguito): una sola
    return pagina


def test_senza_pagine_dichiarate_il_service_worker_resta_quello_di_prima(client, monkeypatch):
    monkeypatch.setattr(hooks, "_senza_rete", [])
    elenco, codice = _elenco(client)
    assert elenco == {"pagine": [], "statici": []}
    assert "showNotification" in codice and "caches.match(OFFLINE)" in codice and "{{" not in codice


def test_la_pagina_dichiarata_e_i_suoi_file_arrivano_al_service_worker(client, scanner):
    elenco, _ = _elenco(client)
    assert elenco["pagine"] == [reverse(scanner)]
    assert len(elenco["statici"]) == 1 and elenco["statici"][0].startswith("/static/core/push") and "push" in elenco["statici"][0]


def test_con_il_modulo_spento_o_una_pagina_che_non_esiste_niente(client, scanner, monkeypatch):
    hooks.pagina_senza_rete("modulo:che_non_c_e", statici=["core/push.js"])
    assert _elenco(client)[0]["pagine"] == [reverse(scanner)]
    monkeypatch.setattr(modules, "disattivati", lambda: frozenset({"crm"}))
    assert _elenco(client)[0] == {"pagine": [], "statici": []}


def test_un_progetto_senza_il_kernel_ha_il_service_worker_di_sempre(client, scanner, settings):
    settings.THEME = {k: v for k, v in settings.THEME.items() if k != "senza_rete"}
    assert _elenco(client)[0] == {"pagine": [], "statici": []}
    settings.THEME = {**settings.THEME, "senza_rete": "modulo.che.non.esiste"}
    assert _elenco(client)[0] == {"pagine": [], "statici": []}
