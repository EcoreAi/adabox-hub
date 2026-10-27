import json
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.urls import URLResolver, reverse

import todo
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi
from core.registry.urls import patterns_moduli
from todo.models import Attivita, Tag

CARTELLA = Path(todo.__file__).parent


@pytest.fixture
def gruppi(db):
    return crea_gruppi(manifest.leggi(CARTELLA))


@pytest.fixture
def membro(gruppi, client):
    u = User.objects.create_user("lucia", "lucia@example.com", "pass12345!")
    u.groups.add(Group.objects.get(name="To-Do / Utente"))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


@pytest.fixture
def aziende(membro):
    prima = membro.profilo.azienda_predefinita
    seconda = Azienda.objects.create(nome="Zeta Srl")
    membro.profilo.aziende.add(seconda)
    Attivita.objects.create(azienda=prima, titolo="Mia attività")
    altra = Attivita.objects.create(azienda=seconda, titolo="Attività di Zeta")
    return prima, seconda, altra


def test_manifest_valido():
    m = manifest.leggi(CARTELLA)
    assert m.slug == "todo" and m.application and m.hooks == "todo.hooks"


@pytest.mark.django_db
def test_modelli():
    a = Attivita.objects.create(azienda=Azienda.objects.first(), titolo="Prova")
    a.tag.add(Tag.objects.create(nome="x"))
    assert str(a) == "Prova" and a.stato == Attivita.APERTA and a.tag.count() == 1


def test_url_montati():
    namespaces = [p.namespace for p in patterns_moduli() if isinstance(p, URLResolver)]
    assert "todo" in namespaces
    assert reverse("todo:attivita_lista") == "/todo/attivita/"
    assert reverse("todo:tag_lista") == "/todo/tag/"


def test_fixture_tag_e_demo_coerenti():
    tag = json.loads((CARTELLA / "data" / "tag.json").read_text())
    demo = json.loads((CARTELLA / "data" / "demo.json").read_text())
    assert [t["pk"] for t in tag] == [1, 2, 3]
    assert len(demo) == 10 and all(d["fields"]["azienda"] == 1 for d in demo)
    assert {t for d in demo for t in d["fields"]["tag"]} <= {1, 2, 3}


def test_lista_nuovo_dettaglio(client, membro, aziende):
    prima, seconda, altra = aziende
    html = client.get("/todo/attivita/").content.decode()
    assert "Mia attività" in html and "Attività di Zeta" not in html
    assert 'class="ui-appbar"' in html and "To-Do" in html
    r = client.post("/todo/attivita/nuovo/", {"titolo": "Nuova", "stato": "aperta"})
    nuova = Attivita.objects.get(titolo="Nuova")
    assert r.status_code == 302 and nuova.azienda == prima and nuova.creato_da == membro
    assert client.get(f"/todo/attivita/{nuova.pk}/").status_code == 200
    assert client.get(f"/todo/attivita/{altra.pk}/").status_code == 404


def test_utente_senza_delete(client, membro, aziende):
    prima, _, _ = aziende
    a = Attivita.objects.get(titolo="Mia attività")
    assert client.post(f"/todo/attivita/{a.pk}/elimina/").status_code == 403


def test_api_con_x_azienda(client, membro, aziende):
    prima, seconda, _ = aziende
    titoli = [a["titolo"] for a in client.get("/api/v1/todo/attivita/", HTTP_X_AZIENDA=str(seconda.pk)).json()["results"]]
    assert titoli == ["Attività di Zeta"]
    altra = client.get("/api/v1/todo/attivita/").json()["results"]
    assert [a["titolo"] for a in altra] == ["Mia attività"] and altra[0]["azienda"] == prima.pk


def test_azione_e_bottone(client, membro, aziende):
    a = Attivita.objects.get(titolo="Mia attività")
    client.post(f"/todo/attivita/{a.pk}/bottone/segna_fatta/")
    a.refresh_from_db()
    assert a.stato == Attivita.FATTA
    client.post("/todo/attivita/azione/archivia/", {"pk": [a.pk]})
    a.refresh_from_db()
    assert a.stato == Attivita.ANNULLATA


def test_launcher_e_nav(client, membro):
    r = client.get("/")
    assert "To-Do" in r.content.decode() and "todo/icon.svg" in r.content.decode()
    assert [v["label"] for v in r.context["theme"]["nav"]] == ["To-Do"]
    estraneo = User.objects.create_user("estraneo", "e@example.com", "pass12345!")
    client.force_login(estraneo)
    r = client.get("/")
    assert r.context["theme"]["nav"] == [] and "todo/icon.svg" not in r.content.decode()


@pytest.mark.django_db
def test_hook_post_install(gruppi):
    from todo import hooks
    attivo = User.objects.create_user("attivo", "a@example.com", "pass12345!")
    spento = User.objects.create_user("spento", "s@example.com", "pass12345!", is_active=False)
    hooks.post_install(None)
    assert attivo.groups.filter(name="To-Do / Utente").exists()
    assert not spento.groups.exists()
