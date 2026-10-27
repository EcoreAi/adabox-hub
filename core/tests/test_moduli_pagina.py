import json
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib import admin
from django.urls import reverse

from core.models import Modulo


@pytest.fixture
def addons(addons_tmp, settings, tmp_path):
    settings.LOG_DIR = tmp_path / "logs"
    addons_tmp.crea("alfa", summary="Modulo alfa", demo=[])
    addons_tmp.crea("beta")
    addons_tmp.crea("gamma", version="2.0.0")
    addons_tmp.crea("delta")
    (addons_tmp.dir / "installed.json").write_text(
        json.dumps({"schema": 1, "installed": ["beta", "gamma", "sparito", "delta"]}))
    Modulo.objects.create(slug="gamma", nome="Gamma", versione_installata="1.0.0")
    Modulo.objects.create(slug="delta", nome="Delta", versione_installata="1.0.0", stato=Modulo.ERRORE,
                          ultimo_errore="migrazione fallita")
    return addons_tmp


@pytest.fixture
def popen(monkeypatch):
    chiamate = []

    class Finto:
        def __init__(self, cmd, **kw):
            chiamate.append((cmd, kw))
    monkeypatch.setattr(subprocess, "Popen", Finto)
    return chiamate


@pytest.mark.django_db
def test_accesso(client, staff):
    client.logout()
    assert client.get("/moduli/").status_code == 302
    client.force_login(staff)
    assert client.get("/moduli/").status_code == 403


def _scheda(html, nome):
    i = html.index(f'<div class="ui-card-title">{nome}</div>')
    return html[i:html.find('class="ui-card is-revealed ui-modulo"', i)]


@pytest.mark.django_db
def test_pagina_con_le_schede(client, superuser, addons):
    r = client.get("/moduli/")
    assert r.status_code == 200
    html = r.content.decode()
    alfa = _scheda(html, "Alfa")
    assert "Modulo alfa" in alfa and 'value="installa"' in alfa and "Disponibile" in alfa
    beta = _scheda(html, "Beta")
    assert 'value="disinstalla"' in beta and 'name="elimina_dati"' in beta and 'value="installa"' not in beta
    gamma = _scheda(html, "Gamma")
    assert 'value="aggiorna"' in gamma and 'value="disinstalla"' in gamma and "v2.0.0" in gamma
    sparito = _scheda(html, "sparito")
    assert "Mancante" in sparito and 'value="disinstalla"' in sparito and 'value="installa"' not in sparito
    delta = _scheda(html, "Delta")
    assert "ui-alert" in delta and "migrazione fallita" in delta


@pytest.mark.django_db
def test_azione_installa(client, superuser, addons, popen, settings):
    r = client.post("/moduli/azione/", {"op": "installa", "slug": "alfa"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200
    ((cmd, kw),) = popen
    assert cmd == [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "modulo", "installa", "alfa",
                   "--si", "--riavvia"]
    assert kw["start_new_session"] is True and kw["stderr"] == subprocess.STDOUT
    assert Path(kw["stdout"].name).parent == settings.LOG_DIR
    nome = Path(kw["stdout"].name).name
    assert f"/moduli/stato/?log={nome}" in r.content.decode() and "hx-get" in r.content.decode()


@pytest.mark.django_db
def test_azione_opzioni(client, superuser, addons, popen):
    client.post("/moduli/azione/", {"op": "installa", "slug": "alfa", "demo": "1"})
    client.post("/moduli/azione/", {"op": "disinstalla", "slug": "beta", "elimina_dati": "1"})
    client.post("/moduli/azione/", {"op": "disinstalla", "slug": "sparito"})
    assert popen[0][0][-1] == "--demo"
    assert popen[1][0][-3:] == ["--si", "--riavvia", "--elimina-dati"]
    assert popen[2][0][3:5] == ["disinstalla", "sparito"]


@pytest.mark.django_db
def test_azione_non_valida(client, superuser, addons, popen):
    assert client.post("/moduli/azione/", {"op": "installa", "slug": "inesistente"}).status_code == 400
    assert client.post("/moduli/azione/", {"op": "formatta", "slug": "alfa"}).status_code == 400
    assert popen == []


@pytest.mark.django_db
def test_stato(client, superuser, settings, tmp_path):
    settings.LOG_DIR = tmp_path
    nome = "moduli-alfa-20261027-120000.log"
    (tmp_path / nome).write_text("".join(f"riga {i}\n" for i in range(100)))
    r = client.get("/moduli/stato/", {"log": nome})
    html = r.content.decode()
    assert "riga 99" in html and "riga 39\n" not in html and "riga 40" in html
    assert 'hx-trigger="every 2s"' in html
    (tmp_path / nome).write_text("migrate...\n== FINE ok ==\n")
    html = client.get("/moduli/stato/", {"log": nome}).content.decode()
    assert "Operazione completata" in html and "every 2s" not in html
    (tmp_path / nome).write_text("== FINE errore ==\nCommandError: boom\n")
    assert "Operazione fallita" in client.get("/moduli/stato/", {"log": nome}).content.decode()


@pytest.mark.django_db
def test_stato_nome_non_valido(client, superuser):
    for nome in ("../settings.py", "moduli-a/b-20261027-120000.log", "x.log"):
        assert client.get("/moduli/stato/", {"log": nome}).status_code == 400


def test_modulo_admin_sola_lettura():
    ma = admin.site._registry[Modulo]
    assert ma.has_add_permission(None) is False and ma.has_change_permission(None) is False
    assert "stato" in ma.list_display


@pytest.mark.django_db
def test_comando_scrive_fine(addons_tmp, capsys):
    from django.core.management import CommandError, call_command
    with pytest.raises(CommandError):
        call_command("modulo", "installa", "inesistente", "--si")
    assert "== FINE errore ==" in capsys.readouterr().out


@pytest.mark.django_db
def test_launcher_vuoto_superuser_link_moduli(client, superuser, monkeypatch):
    from core.registry import modules
    monkeypatch.setattr(modules, "manifests_attivi", lambda: {})
    html = client.get(reverse("core:home")).content.decode()
    assert 'href="/moduli/">Installa un modulo' in html
