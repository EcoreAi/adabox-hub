import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core.models import Azienda
from core.views import AziendaView
from core.viste import registry

URL = "/core/aziende/"


def _utente(*perms):
    u = User.objects.create_user("lettore", "l@example.com", "pass12345!")
    for p in perms:
        app, codename = p.split(".")
        u.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def vista(monkeypatch):
    v = registry.per_modello(Azienda)
    monkeypatch.setattr(v, "per_page", 5)
    return v


@pytest.fixture
def lettore(db, client, vista):
    u = _utente("core.view_azienda")
    client.force_login(u)
    return u


@pytest.fixture
def aziende(db):
    Azienda.objects.create(nome="Acme Spa", partita_iva="01234567890", citta="Cagliari", provincia="CA")
    Azienda.objects.create(nome="Beta Srl", partita_iva="999", citta="", provincia="MI", attiva=False)
    for i in range(10):
        Azienda.objects.create(nome=f"Ditta {i:02d}", citta="Roma", provincia="RM")


def test_nomi_url():
    assert reverse("core:aziende_lista") == URL
    assert reverse("core:aziende_dettaglio", kwargs={"pk": 3}) == "/core/aziende/3/"


def test_registro():
    v = registry.per_modello(Azienda)
    assert isinstance(v, AziendaView) and v in registry.viste_di("core")
    assert len(registry.urlpatterns("core")) == 7


@pytest.mark.django_db
def test_anonimo_al_login(client):
    assert client.get(URL).status_code == 302


@pytest.mark.django_db
def test_senza_permesso_403(client, utente):
    client.force_login(utente)
    assert client.get(URL).status_code == 403


def test_con_permesso_righe(client, lettore, aziende):
    r = client.get(URL)
    assert r.status_code == 200
    html = r.content.decode()
    assert "Acme Spa" in html and "<html" in html


def _nomi(r):
    return [obj.nome for obj, _ in r.context["righe"]]


def test_ricerca(client, lettore, aziende):
    assert _nomi(client.get(URL, {"q": "acme"})) == ["Acme Spa"]
    assert _nomi(client.get(URL, {"q": "999"})) == ["Beta Srl"]


def test_filtri(client, lettore, aziende):
    assert _nomi(client.get(URL, {"f_attiva": "0"})) == ["Beta Srl"]
    assert _nomi(client.get(URL, {"f_provincia": "CA"})) == ["Acme Spa"]
    assert _nomi(client.get(URL, {"f_attiva": "x"}))  # valore non valido: ignorato


def test_ordinamento(client, lettore, aziende):
    assert _nomi(client.get(URL, {"o": "-nome"}))[0] == "Ditta 09"
    assert _nomi(client.get(URL, {"o": "telefono"}))[0] == "Acme Spa"   # non in list_display: ignorato


def test_paginazione_conserva_i_parametri(client, lettore, aziende):
    r = client.get(URL, {"q": "ditta", "f_provincia": "RM", "o": "-nome", "p": 2})
    assert _nomi(r) == ["Ditta 04", "Ditta 03", "Ditta 02", "Ditta 01", "Ditta 00"]
    html = r.content.decode()
    assert "q=ditta" in html and "f_provincia=RM" in html and "o=-nome" in html and "p=1" in html


def test_parziale(client, lettore, aziende):
    for r in (client.get(URL, {"partial": 1}), client.get(URL, HTTP_HX_REQUEST="true")):
        html = r.content.decode()
        assert "<html" not in html and 'id="tabella"' in html


def test_celle(client, lettore, aziende):
    html = client.get(URL, {"q": "a"}).content.decode()
    assert "CAGLIARI" in html               # col_citta
    assert "ui-pill" in html                # attiva
    assert "—" in html                      # citta vuota


def test_bottone_nuovo_solo_con_add(client, lettore, aziende):
    assert reverse("core:aziende_nuovo") not in client.get(URL).content.decode()
    client.force_login(_utente_add())
    assert reverse("core:aziende_nuovo") in client.get(URL).content.decode()


def _utente_add():
    u = User.objects.create_user("autore", "a@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(codename__in=["view_azienda", "add_azienda"]))
    return User.objects.get(pk=u.pk)
