import pytest
from django.contrib.auth.models import User

from core.models import Lavoro

pytestmark = [pytest.mark.urls("core.tests.urls_viste"), pytest.mark.django_db]


@pytest.fixture
def lavori(db):
    for funzione, stato, tentativi in [("a.uno", "in_coda", 0), ("a.due", "in_coda", 1), ("b.tre", "fatto", 2)]:
        Lavoro.objects.create(funzione=funzione, stato=stato, tentativi=tentativi)


def test_colonne_e_card(client, superuser, lavori):
    r = client.get("/prova/lavori/kanban/")
    assert r.status_code == 200
    colonne = {c["valore"]: c for c in r.context["colonne"]}
    assert list(colonne) == ["in_coda", "in_corso", "fatto", "fallito"]
    assert colonne["in_coda"]["totale"] == 2 and colonne["fatto"]["card"][0]["obj"].funzione == "b.tre"
    html = r.content.decode()
    assert 'draggable="true"' in html and "core/kanban.js" in html and "ui-selettore" in html


def test_filtri_applicati(client, superuser, lavori):
    r = client.get("/prova/lavori/kanban/", {"q": "a."})
    assert sum(c["totale"] for c in r.context["colonne"]) == 2


def test_limite_e_altri(client, superuser, lavori, monkeypatch):
    from core.tests.urls_viste import VISTA
    monkeypatch.setattr(VISTA, "kanban_limite", 1)
    col = next(c for c in client.get("/prova/lavori/kanban/").context["colonne"] if c["valore"] == "in_coda")
    assert len(col["card"]) == 1 and col["altri"] == 1


def test_sposta(client, superuser, lavori):
    lavoro = Lavoro.objects.get(funzione="a.uno")
    r = client.post(f"/prova/lavori/{lavoro.pk}/sposta/", {"valore": "fatto"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 204
    lavoro.refresh_from_db()
    assert lavoro.stato == "fatto"
    r = client.post(f"/prova/lavori/{lavoro.pk}/sposta/", {"valore": "fallito", "ritorno": "q=a."})
    assert r.status_code == 302 and r["Location"] == "/prova/lavori/kanban/?q=a."


def test_sposta_valore_non_valido_e_permessi(client, superuser, lavori):
    lavoro = Lavoro.objects.get(funzione="a.uno")
    assert client.post(f"/prova/lavori/{lavoro.pk}/sposta/", {"valore": "volato"}).status_code == 400
    client.force_login(User.objects.create_user("normale", "n@example.com", "x"))
    assert client.post(f"/prova/lavori/{lavoro.pk}/sposta/", {"valore": "fatto"}).status_code == 403
    assert client.get("/prova/lavori/kanban/").status_code == 403


def test_lista_mostra_il_selettore(client, superuser, lavori):
    html = client.get("/prova/lavori/").content.decode()
    assert 'href="/prova/lavori/kanban/"' in html


def test_sposta_tracciato_nel_chatter(client, superuser, lavori, monkeypatch):
    from core import chatter
    from core.tests.urls_viste import VISTA
    monkeypatch.setattr(VISTA, "chatter", True)
    monkeypatch.setattr(VISTA, "tracked_fields", ["stato"])
    lavoro = Lavoro.objects.get(funzione="a.uno")
    client.post(f"/prova/lavori/{lavoro.pk}/sposta/", {"valore": "fatto"}, HTTP_HX_REQUEST="true")
    (m,) = chatter.messaggi_di(lavoro)
    assert m.modifiche == [{"campo": "stato", "label": "Stato", "prima": "In coda", "dopo": "Fatto"}]
