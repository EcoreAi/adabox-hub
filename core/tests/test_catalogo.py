import pytest
from django.core.management import call_command

from core.registry import pacchetti
from core.registry.pacchetti import PacchettoNonValido
from core.tests.conftest_aiuti import crea_modulo


@pytest.fixture
def chiave(settings):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    privata = Ed25519PrivateKey.generate()
    settings.MODULI_CHIAVI_FIDATE = [pacchetti.pubblica_b64(privata)]
    settings.MODULI_FIRMA_OBBLIGATORIA = True
    return privata


@pytest.fixture
def catalogo(tmp_path, chiave, settings, addons_tmp):
    settings.BACKUP_DIR = tmp_path / "backup"
    dist = tmp_path / "dist"
    for slug, versione in [("gamma", "1.0.0"), ("gamma", "1.2.0"), ("delta", "2.0.0")]:
        cartella = crea_modulo(tmp_path / f"src-{slug}-{versione}", slug, version=versione, summary=f"Modulo {slug}")
        pacchetti.impacchetta(cartella, dist, chiave)
    non_firmato = crea_modulo(tmp_path / "src-epsilon", "epsilon")
    pacchetti.impacchetta(non_firmato, dist)
    assert pacchetti.crea_indice(dist, chiave) == 3
    settings.MODULI_CATALOGO_URL = (dist / "indice.json").as_uri()
    return dist


@pytest.mark.django_db
def test_voci_del_catalogo(catalogo, addons_tmp):
    crea_modulo(addons_tmp.dir, "delta", version="2.0.0")
    voci = {v["slug"]: v for v in pacchetti.leggi_catalogo()}
    assert set(voci) == {"gamma", "delta"}                              # epsilon non firmato: fuori
    assert voci["gamma"]["versione"] == "1.2.0" and voci["gamma"]["stato"] == "nuovo"
    assert voci["delta"]["stato"] == "presente" and voci["gamma"]["riassunto"] == "Modulo gamma"


@pytest.mark.django_db
def test_scarica(catalogo, addons_tmp):
    esito = pacchetti.scarica("gamma")
    assert (esito.slug, esito.versione) == ("gamma", "1.2.0") and (addons_tmp.dir / "gamma").exists()
    assert pacchetti.origine(addons_tmp.dir / "gamma")["pacchetto"] == "gamma-1.2.0.zip"
    with pytest.raises(PacchettoNonValido, match="non è nel catalogo"):
        pacchetti.scarica("zeta")


@pytest.mark.django_db
def test_indice_alterato(catalogo):
    indice = catalogo / "indice.json"
    indice.write_bytes(indice.read_bytes().replace(b"Modulo gamma", b"Modulo truffa"))
    with pytest.raises(PacchettoNonValido, match="firma valida"):
        pacchetti.leggi_catalogo()


@pytest.mark.django_db
def test_pacchetto_scambiato(catalogo):
    (catalogo / "gamma-1.2.0.zip").write_bytes((catalogo / "gamma-1.0.0.zip").read_bytes())
    with pytest.raises(PacchettoNonValido, match="non corrisponde al catalogo"):
        pacchetti.scarica("gamma")


@pytest.mark.django_db
def test_catalogo_irraggiungibile(settings, chiave):
    settings.MODULI_CATALOGO_URL = "file:///non/esiste/indice.json"
    with pytest.raises(PacchettoNonValido, match="non raggiungibile"):
        pacchetti.leggi_catalogo()


@pytest.mark.django_db
def test_pagina(client, superuser, catalogo, addons_tmp):
    html = client.get("/moduli/").content.decode()
    assert "Catalogo" in html and "gamma" in html and "Scarica" in html
    r = client.post("/moduli/scarica/", {"slug": "gamma"})
    assert r.status_code == 302 and (addons_tmp.dir / "gamma").exists()


@pytest.mark.django_db
def test_comando_indice(tmp_path, chiave, capsys):
    file_chiave = tmp_path / "c.pem"
    from cryptography.hazmat.primitives import serialization
    file_chiave.write_bytes(chiave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
    pacchetti.impacchetta(crea_modulo(tmp_path / "src", "zeta"), tmp_path / "dist", chiave)
    call_command("modulo", "indice", str(tmp_path / "dist"), "--firma", str(file_chiave), "--url-base", "https://x.it/m")
    assert "1 pacchetti" in capsys.readouterr().out
    assert b'"url":"https://x.it/m/zeta-1.0.0.zip"' in (tmp_path / "dist" / "indice.json").read_bytes()
