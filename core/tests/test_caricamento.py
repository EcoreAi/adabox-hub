import io
import json
import stat
import zipfile

import pytest
from django.core.management import CommandError, call_command

from core.models import Modulo
from core.registry import pacchetti
from core.registry.pacchetti import PacchettoNonValido


@pytest.fixture
def chiave(settings):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    privata = Ed25519PrivateKey.generate()
    pubblica = pacchetti.pubblica_b64(privata)
    settings.MODULI_CHIAVI_FIDATE = [pubblica]
    settings.MODULI_FIRMA_OBBLIGATORIA = True
    return privata


@pytest.fixture
def sorgente(tmp_path, addons_tmp, settings):
    """Il modulo 'beta' in una cartella sorgente fuori da addons/ (come nel repository di chi lo sviluppa)."""
    settings.BACKUP_DIR = tmp_path / "backup"
    from core.tests.conftest_aiuti import crea_modulo
    return crea_modulo(tmp_path / "sorgenti", "beta")


def _pacchetto(sorgente, tmp_path, chiave=None):
    return pacchetti.impacchetta(sorgente, tmp_path / "dist", chiave)


@pytest.mark.django_db
def test_carica_firmato(sorgente, chiave, tmp_path, addons_tmp):
    esito = pacchetti.carica(_pacchetto(sorgente, tmp_path, chiave))
    assert (esito.slug, esito.versione) == ("beta", "1.0.0") and esito.firmato_da
    assert (addons_tmp.dir / "beta" / "__manifest__.py").exists()
    origine = pacchetti.origine(addons_tmp.dir / "beta")
    assert origine["firmato_da"] == esito.firmato_da and origine["pacchetto"] == "beta-1.0.0.zip"
    assert Modulo.objects.get(slug="beta").stato == Modulo.DISPONIBILE                 # caricato, non installato


@pytest.mark.django_db
def test_firma_obbligatoria_e_chiave_non_fidata(sorgente, chiave, tmp_path, settings):
    with pytest.raises(PacchettoNonValido, match="firma è obbligatoria"):
        pacchetti.carica(_pacchetto(sorgente, tmp_path))
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    with pytest.raises(PacchettoNonValido, match="non fidata"):
        pacchetti.carica(_pacchetto(sorgente, tmp_path, Ed25519PrivateKey.generate()))
    settings.MODULI_FIRMA_OBBLIGATORIA = False
    assert pacchetti.carica(_pacchetto(sorgente, tmp_path)).avvisi == ["pacchetto non firmato"]


def _riscrivi(zip_, modifica):
    """Copia dello zip con le voci modificate da modifica(nome, dati) -> (nome, dati) o None per toglierla."""
    voci = []
    with zipfile.ZipFile(zip_) as z:
        for v in z.infolist():
            nuovo = modifica(v.filename, z.read(v))
            if nuovo:
                voci.append(nuovo)
    with zipfile.ZipFile(zip_, "w") as z:
        for nome, dati in voci:
            z.writestr(nome, dati)
    return zip_


@pytest.mark.django_db
def test_file_alterato(sorgente, chiave, tmp_path):
    zip_ = _riscrivi(_pacchetto(sorgente, tmp_path, chiave),
                     lambda n, d: (n, d + b"\n# aggiunto" if n == "beta/models.py" else d))
    with pytest.raises(PacchettoNonValido, match="alterato"):
        pacchetti.carica(zip_)


@pytest.mark.django_db
@pytest.mark.parametrize("nome", ["../fuori.py", "/assoluto.py", "beta/../../fuori.py", "C:/win.py"])
def test_percorsi_non_ammessi(sorgente, chiave, tmp_path, nome):
    zip_ = _pacchetto(sorgente, tmp_path, chiave)
    with zipfile.ZipFile(zip_, "a") as z:
        z.writestr(nome, b"x")
    with pytest.raises(PacchettoNonValido, match="non ammesso"):
        pacchetti.carica(zip_)


@pytest.mark.django_db
def test_link_simbolico(sorgente, chiave, tmp_path):
    zip_ = _pacchetto(sorgente, tmp_path, chiave)
    with zipfile.ZipFile(zip_, "a") as z:
        info = zipfile.ZipInfo("beta/link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "/etc/passwd")
    with pytest.raises(PacchettoNonValido, match="link simbolico"):
        pacchetti.carica(zip_)


@pytest.mark.django_db
def test_zip_bomb_e_dimensione(sorgente, chiave, tmp_path, monkeypatch, settings):
    monkeypatch.setattr(pacchetti, "MAX_DECOMPRESSO", 10)
    with pytest.raises(PacchettoNonValido, match="troppo grande"):
        pacchetti.carica(_pacchetto(sorgente, tmp_path, chiave))
    settings.MODULI_ZIP_MAX_MB = 0
    with pytest.raises(PacchettoNonValido, match="supera"):
        pacchetti.carica(_pacchetto(sorgente, tmp_path, chiave))


@pytest.mark.django_db
def test_non_zip_e_senza_descrizione(tmp_path, chiave):
    falso = tmp_path / "x.zip"
    falso.write_bytes(b"non sono uno zip")
    with pytest.raises(PacchettoNonValido, match="zip valido"):
        pacchetti.carica(falso)
    vuoto = tmp_path / "vuoto.zip"
    with zipfile.ZipFile(vuoto, "w") as z:
        z.writestr("beta/__init__.py", "")
    with pytest.raises(PacchettoNonValido, match="manca"):
        pacchetti.carica(vuoto)


@pytest.mark.django_db
def test_cartella_radice_sbagliata(sorgente, chiave, tmp_path):
    zip_ = _pacchetto(sorgente, tmp_path, chiave)
    with zipfile.ZipFile(zip_, "a") as z:
        z.writestr("intruso/x.py", b"x")
    with pytest.raises(PacchettoNonValido, match="solo la cartella"):
        pacchetti.carica(zip_)


@pytest.mark.django_db
def test_slug_riservato(tmp_path, chiave, addons_tmp):
    from core.tests.conftest_aiuti import crea_modulo
    cartella = crea_modulo(tmp_path / "sorgenti", "admin")
    descrizione = {"formato": 1, "slug": "admin", "versione": "1.0.0", "nome": "Admin", "min_core": "1.0",
                   "creato": "x", "file": {p: pacchetti._sha256(cartella / p) for p in pacchetti.file_del_modulo(cartella)}}
    dati = pacchetti.serializza(descrizione)
    zip_ = tmp_path / "admin.zip"
    with zipfile.ZipFile(zip_, "w") as z:
        for rel in descrizione["file"]:
            z.write(cartella / rel, f"admin/{rel}")
        z.writestr("adabox-modulo.json", dati)
        z.writestr("adabox-modulo.sig", pacchetti.firma(dati, chiave))
    with pytest.raises(PacchettoNonValido, match="riservato"):
        pacchetti.carica(zip_)


@pytest.mark.django_db
def test_versioni(sorgente, chiave, tmp_path, addons_tmp, settings):
    pacchetti.carica(_pacchetto(sorgente, tmp_path, chiave))
    with pytest.raises(PacchettoNonValido, match="già presente"):
        pacchetti.carica(_pacchetto(sorgente, tmp_path, chiave))
    pacchetti.carica(_pacchetto(sorgente, tmp_path, chiave), forza=True)
    manifest = sorgente / "__manifest__.py"
    manifest.write_text(manifest.read_text().replace("1.0.0", "1.1.0"))
    pacchetti.carica(_pacchetto(sorgente, tmp_path, chiave))
    assert "1.1.0" in (addons_tmp.dir / "beta" / "__manifest__.py").read_text()
    archivi = sorted(p.name for p in (settings.BACKUP_DIR / "moduli").iterdir())
    assert len(archivi) == 2 and all(a.startswith("beta-1.0.0-") for a in archivi)
    manifest.write_text(manifest.read_text().replace("1.1.0", "0.9.0"))
    with pytest.raises(PacchettoNonValido, match="presente la 1.1.0"):
        pacchetti.carica(_pacchetto(sorgente, tmp_path, chiave))


@pytest.mark.django_db
def test_comando_carica(sorgente, chiave, tmp_path, capsys):
    zip_ = _pacchetto(sorgente, tmp_path, chiave)
    call_command("modulo", "carica", str(zip_))
    assert "Caricato beta 1.0.0" in capsys.readouterr().out
    with pytest.raises(CommandError, match="già presente"):
        call_command("modulo", "carica", str(zip_))


@pytest.mark.django_db
def test_pagina_carica(client, superuser, sorgente, chiave, tmp_path, addons_tmp):
    from django.core.files.uploadedfile import SimpleUploadedFile
    zip_ = _pacchetto(sorgente, tmp_path, chiave)
    r = client.post("/moduli/carica/", {"pacchetto": SimpleUploadedFile("beta-1.0.0.zip", zip_.read_bytes())})
    assert r.status_code == 302 and (addons_tmp.dir / "beta").exists()
    html = client.get("/moduli/").content.decode()
    assert "Carica un modulo" in html and "Firmato da" in html
    r = client.post("/moduli/carica/", {"pacchetto": SimpleUploadedFile("x.zip", b"rotto")}, follow=True)
    assert "zip valido" in r.content.decode()
    from django.contrib.auth.models import User
    client.force_login(User.objects.create_user("staff2", "s@example.com", "x", is_staff=True))
    assert client.post("/moduli/carica/").status_code == 403
