import json
import zipfile

import pytest
from django.core.management import call_command

from core.registry import pacchetti


@pytest.fixture
def chiave():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    privata = Ed25519PrivateKey.generate()
    return privata, pacchetti.pubblica_b64(privata)


@pytest.fixture
def modulo(addons_tmp):
    cartella = addons_tmp.crea("alfa", summary="Prova")
    (cartella / "__pycache__").mkdir()
    (cartella / "__pycache__" / "x.cpython-313.pyc").write_bytes(b"x")
    (cartella / ".segreto").write_text("no")
    (cartella / "templates" / "alfa").mkdir(parents=True)
    (cartella / "templates" / "alfa" / "pagina.html").write_text("<p>ciao</p>")
    return cartella


def test_descrizione_ed_esclusioni(modulo):
    d = pacchetti.descrivi(modulo)
    assert (d["slug"], d["versione"], d["formato"]) == ("alfa", "1.0.0", 1)
    assert "templates/alfa/pagina.html" in d["file"] and "__manifest__.py" in d["file"]
    assert not any("__pycache__" in f or f.startswith(".") for f in d["file"])


def test_impacchetta_firmato(modulo, chiave, tmp_path):
    privata, pubblica = chiave
    zip_ = pacchetti.impacchetta(modulo, tmp_path / "dist", privata)
    assert zip_.name == "alfa-1.0.0.zip"
    with zipfile.ZipFile(zip_) as z:
        nomi = set(z.namelist())
        assert {"adabox-modulo.json", "adabox-modulo.sig", "alfa/__manifest__.py"} <= nomi
        dati, firma = z.read("adabox-modulo.json"), z.read("adabox-modulo.sig")
    assert pacchetti.verifica(dati, firma, [pubblica]) == pubblica
    assert pacchetti.verifica(dati + b" ", firma, [pubblica]) is None                 # dati alterati
    altra = pacchetti.genera_chiavi()[1]
    assert pacchetti.verifica(dati, firma, [altra]) is None                           # chiave non fidata
    assert pacchetti.verifica(dati, b"spazzatura!", [pubblica]) is None
    assert json.loads(dati)["file"]["__manifest__.py"]


def test_impronta(chiave):
    _, pubblica = chiave
    imp = pacchetti.impronta(pubblica)
    assert len(imp) == 19 and imp.count(":") == 3


def test_comandi_chiavi_e_impacchetta(modulo, tmp_path, capsys, settings):
    file_chiave = tmp_path / "chiave.pem"
    call_command("modulo", "chiavi", "--uscita", str(file_chiave))
    uscita = capsys.readouterr().out
    assert file_chiave.exists() and (file_chiave.stat().st_mode & 0o777) == 0o600 and "Impronta" in uscita
    call_command("modulo", "impacchetta", "alfa", "--firma", str(file_chiave), "--uscita", str(tmp_path / "dist"))
    assert "firmato" in capsys.readouterr().out and (tmp_path / "dist" / "alfa-1.0.0.zip").exists()
    from django.core.management import CommandError
    with pytest.raises(CommandError):
        call_command("modulo", "chiavi", "--uscita", str(file_chiave))                 # non sovrascrive
