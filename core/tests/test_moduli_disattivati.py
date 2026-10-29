"""Interruttore dei moduli: installato ma spento per tutti (menu, pagine, API, pianificazioni, assistente)."""
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone

from core import lavori
from core.models import Modulo, Pianificazione
from core.registry import hooks, modules

pytestmark = pytest.mark.skipif("todo" not in settings.ADDONS_ATTIVI, reason="serve l'app todo")


@pytest.fixture
def installati(monkeypatch):
    monkeypatch.setattr(modules, "installati", lambda: list(settings.ADDONS_ATTIVI))


def _voci(client):
    return [v["label"] for v in client.get("/dashboard/").context["theme"]["nav"]]


def test_spento_sparisce_e_le_pagine_rispondono_404(client, superuser, installati):
    assert "To-Do" in _voci(client) and client.get("/todo/attivita/").status_code == 200
    assert modules.imposta_attivo("todo", False)
    assert modules.disattivati() == {"todo"}
    assert "To-Do" not in _voci(client)
    assert "To-Do" not in client.get("/app/").content.decode()
    r = client.get("/todo/attivita/")
    assert r.status_code == 404 and "Modulo disattivato" in r.content.decode()
    assert client.get("/api/v1/todo/attivita/").status_code == 404
    assert client.get("/dashboard/").status_code == 200 and client.get("/moduli/").status_code == 200
    assert modules.imposta_attivo("todo", True)
    assert "To-Do" in _voci(client) and client.get("/todo/attivita/").status_code == 200
    assert not modules.imposta_attivo("inesistente", False)


def test_pianificazioni_ferme_finche_e_spento(db, installati):
    Pianificazione.objects.create(modulo="todo", nome="Prova", funzione="core.tests.lavori_prova.ok", ogni="1m",
                                  prossima_esecuzione=timezone.now())
    modules.imposta_attivo("todo", False)
    assert "Prova" not in [p.nome for p in lavori.pianifica_scadute()]
    modules.imposta_attivo("todo", True)
    assert "Prova" in [p.nome for p in lavori.pianifica_scadute()]


def test_voci_della_testata_del_modulo_spento(rf, db, installati):
    hooks.voce_testata("todo/_voce_prova.html")
    try:
        richiesta = rf.get("/")
        richiesta.user = User.objects.create_superuser("root", "r@example.com", "x")
        assert "todo/_voce_prova.html" in [v["template"] for v in hooks.voci_testata(richiesta)]
        modules.imposta_attivo("todo", False)
        assert "todo/_voce_prova.html" not in [v["template"] for v in hooks.voci_testata(richiesta)]
    finally:
        hooks._testata[:] = [v for v in hooks._testata if v["template"] != "todo/_voce_prova.html"]


def test_pagina_moduli_e_comando(client, superuser, installati, capsys):
    r = client.post("/moduli/attivazione/", {"slug": "todo", "attivo": "0"})
    assert r.status_code == 302 and Modulo.objects.get(slug="todo").disattivato
    html = client.get("/moduli/").content.decode()
    assert "Disattivato" in html and "Riattiva" in html
    client.post("/moduli/attivazione/", {"slug": "todo", "attivo": "1"})
    assert not Modulo.objects.get(slug="todo").disattivato
    call_command("modulo", "disattiva", "todo")
    assert "todo disattivato." in capsys.readouterr().out and modules.disattivati() == {"todo"}
    call_command("modulo", "riattiva", "todo")
    assert modules.disattivati() == set()
    utente = User.objects.create_user("utente", password="x")
    client.force_login(utente)
    assert client.post("/moduli/attivazione/", {"slug": "todo", "attivo": "0"}).status_code == 403


@pytest.mark.skipif("ai" not in settings.ADDONS_ATTIVI, reason="serve l'app ai")
def test_l_assistente_non_vede_il_modulo_spento(superuser, installati):
    from ai import strumenti
    from ai.models import Conversazione
    from ai.strumenti import viste
    contesto = strumenti.Contesto(utente=superuser, conversazione=Conversazione.objects.create(utente=superuser))
    assert any(v["app"] == "todo" for v in viste.elenco_viste(contesto))
    modules.imposta_attivo("todo", False)
    assert not any(v["app"] == "todo" for v in viste.elenco_viste(contesto))


def test_nessuna_query_per_kernel_e_file(client, django_assert_num_queries, db):
    with django_assert_num_queries(0):
        client.get("/favicon.ico")
