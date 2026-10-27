import json

import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile

from core import chatter
from core.generici import ct_di
from core.models import Allegato, Azienda, Follower, Messaggio, TokenApi
from core.viste import registry


@pytest.fixture(autouse=True)
def privati(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path


def _utente(client=None, *codenames, nome="chat"):
    u = User.objects.create_user(nome, f"{nome}@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    u = User.objects.get(pk=u.pk)
    if client:
        client.force_login(u)
    return u


@pytest.fixture
def acme(db):
    return Azienda.objects.create(nome="Acme", partita_iva="01")


def _tipi(obj):
    return [m.tipo for m in chatter.messaggi_di(obj)]


def test_creazione_dalla_vista(client, db):
    u = _utente(client, "add_azienda", "view_azienda")
    client.post("/core/aziende/nuovo/", {"nome": "Nuova", "attiva": "on"})
    nuova = Azienda.objects.get(nome="Nuova")
    assert _tipi(nuova) == ["sistema"] and chatter.segue(nuova, u)


def test_tracciamento_dalla_vista(client, acme):
    u = _utente(client, "change_azienda", "view_azienda")
    client.post(f"/core/aziende/{acme.pk}/modifica/", {"nome": "Acme Group", "partita_iva": "01", "citta": "Roma"})
    (m,) = chatter.messaggi_di(acme)
    assert m.tipo == "tracciamento" and m.autore == u
    assert {(c["label"], c["prima"], c["dopo"]) for c in m.modifiche} == {("Nome", "Acme", "Acme Group"), ("Attiva", "Sì", "No")}
    client.post(f"/core/aziende/{acme.pk}/modifica/", {"nome": "Acme Group", "partita_iva": "01", "citta": "Milano"})
    assert len(_tipi(acme)) == 1                       # città non tracciata: nessuna voce


def test_tracciamento_dall_api(client, acme):
    u = _utente(None, "change_azienda", "view_azienda")
    _, chiaro = TokenApi.genera(u, "t")
    client.patch(f"/api/v1/core/aziende/{acme.pk}/", json.dumps({"attiva": False}), content_type="application/json",
                 HTTP_AUTHORIZATION=f"Bearer {chiaro}")
    (m,) = chatter.messaggi_di(acme)
    assert m.modifiche == [{"campo": "attiva", "label": "Attiva", "prima": "Sì", "dopo": "No"}]


def test_pannello_nel_dettaglio(client, acme):
    _utente(client, "view_azienda")
    chatter.scrivi(acme, None, "Primo messaggio\nsu due righe")
    html = client.get(f"/core/aziende/{acme.pk}/").content.decode()
    assert 'id="chatter"' in html and "Primo messaggio<br>su due righe" in html and "ui-con-chatter" in html


def test_scrivi_nota_e_messaggio_con_allegato(client, acme):
    u = _utente(client, "view_azienda")
    ct = ct_di(acme).pk
    r = client.post(f"/chatter/{ct}/{acme.pk}/scrivi/", {"corpo": "solo per noi", "tipo": "nota"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and "solo per noi" in r.content.decode()
    client.post(f"/chatter/{ct}/{acme.pk}/scrivi/", {"corpo": "vedi file", "file": SimpleUploadedFile("a.txt", b"x")})
    ultimo = chatter.messaggi_di(acme).first()
    assert ultimo.tipo == "messaggio" and ultimo.allegati.get().nome == "a.txt"
    assert Allegato.objects.count() == 1 and chatter.segue(acme, u)


def test_scrivi_vuoto_non_crea(client, acme):
    _utente(client, "view_azienda")
    client.post(f"/chatter/{ct_di(acme).pk}/{acme.pk}/scrivi/", {"corpo": "  "})
    assert not Messaggio.objects.exists()


def test_permessi(client, acme, monkeypatch):
    _utente(client)
    assert client.post(f"/chatter/{ct_di(acme).pk}/{acme.pk}/scrivi/", {"corpo": "x"}).status_code == 403
    vista = registry.per_modello(Azienda)
    monkeypatch.setattr(vista, "get_queryset", lambda request: Azienda.objects.exclude(pk=acme.pk))
    client.force_login(_utente(None, "view_azienda", nome="altro"))
    assert client.get(f"/chatter/{ct_di(acme).pk}/{acme.pk}/").status_code == 404


def test_segui_e_smetti(client, acme):
    u = _utente(client, "view_azienda")
    url = f"/chatter/{ct_di(acme).pk}/{acme.pk}/segui/"
    client.post(url)
    assert chatter.segue(acme, u)
    client.post(url, {"azione": "smetti"})
    assert not Follower.objects.exists()


def test_paginazione(client, acme):
    _utente(client, "view_azienda")
    for i in range(25):
        chatter.scrivi(acme, None, f"messaggio {i:02d}", tipo="nota")
    html = client.get(f"/core/aziende/{acme.pk}/").content.decode()
    assert "messaggio 24" in html and "messaggio 04" not in html and "Messaggi precedenti" in html
    altri = client.get(f"/chatter/{ct_di(acme).pk}/{acme.pk}/messaggi/?p=2").content.decode()
    assert "messaggio 04" in altri and "messaggio 24" not in altri
