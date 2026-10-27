import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile

from core import allegati
from core.generici import ct_di
from core.models import Allegato, Azienda


@pytest.fixture(autouse=True)
def cartella(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private"
    return settings.PRIVATE_MEDIA_ROOT


def _utente(client, *codenames, nome="all"):
    u = User.objects.create_user(nome, f"{nome}@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="core", codename__in=codenames))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    return u


def _file(nome="nota.txt", contenuto=b"ciao"):
    return SimpleUploadedFile(nome, contenuto)


@pytest.fixture
def acme(db):
    return Azienda.objects.create(nome="Acme")


def test_carica_e_scarica(client, acme, cartella):
    _utente(client, "view_azienda", "change_azienda")
    ct = ct_di(acme).pk
    r = client.post(f"/allegati/carica/{ct}/{acme.pk}/", {"file": [_file(), _file("foto.png", b"\x89PNG")]},
                    HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and "nota.txt" in r.content.decode()
    nota = Allegato.objects.get(nome="nota.txt")
    assert nota.dimensione == 4 and nota.mime == "text/plain" and nota.file.path.startswith(str(cartella))
    r = client.get(f"/allegati/{nota.pk}/")
    assert b"".join(r.streaming_content) == b"ciao" and r["Content-Disposition"].startswith("attachment")
    foto = Allegato.objects.get(nome="foto.png")
    assert client.get(f"/allegati/{foto.pk}/")["Content-Disposition"].startswith("inline")


def test_senza_change_non_carica(client, acme):
    _utente(client, "view_azienda")
    r = client.post(f"/allegati/carica/{ct_di(acme).pk}/{acme.pk}/", {"file": _file()})
    assert r.status_code == 403 and not Allegato.objects.exists()


def test_download_negato(client, acme, utente):
    a = allegati.salva(acme, _file(), utente)
    _utente(client, nome="estraneo")
    assert client.get(f"/allegati/{a.pk}/").status_code == 403
    client.logout()
    assert client.get(f"/allegati/{a.pk}/").status_code == 302


def test_record_di_altra_azienda_404(client, acme, monkeypatch):
    from core.viste import registry
    vista = registry.per_modello(Azienda)
    a = allegati.salva(acme, _file())
    monkeypatch.setattr(vista, "get_queryset", lambda request: Azienda.objects.exclude(pk=acme.pk))
    _utente(client, "view_azienda")
    assert client.get(f"/allegati/{a.pk}/").status_code == 404


def test_limiti(acme, settings):
    with pytest.raises(allegati.AllegatoNonValido, match="non ammessi"):
        allegati.salva(acme, _file("virus.exe"))
    with pytest.raises(allegati.AllegatoNonValido, match="vuoto"):
        allegati.salva(acme, _file(contenuto=b""))
    settings.ALLEGATI_MAX_MB = 0
    with pytest.raises(allegati.AllegatoNonValido, match="MB"):
        allegati.salva(acme, _file())


def test_nome_ripulito(acme):
    a = allegati.salva(acme, _file("../../etc/pass wd;rm.txt"))
    assert a.nome == "pass_wdrm.txt" and ".." not in a.file.name


def test_elimina(client, acme):
    a = allegati.salva(acme, _file())
    percorso = a.file.path
    _utente(client, "view_azienda", "change_azienda")
    client.post(f"/allegati/{a.pk}/elimina/")
    assert not Allegato.objects.exists()
    import os
    assert not os.path.exists(percorso)


def test_x_accel(client, acme, settings):
    settings.ALLEGATI_X_ACCEL = True
    a = allegati.salva(acme, _file())
    _utente(client, "view_azienda")
    r = client.get(f"/allegati/{a.pk}/")
    assert r["X-Accel-Redirect"] == f"/_privati/{a.file.name}" and r.content == b""
    assert 'filename="nota.txt"' in r["Content-Disposition"]
