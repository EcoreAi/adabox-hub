"""Librerie dichiarate dai moduli in «dipendenze» (core.registry.dipendenze): forma nel manifest e controllo
sull'immagine."""
import importlib.metadata
import types

import pytest

from core.registry import dipendenze, manifest
from core.registry.manifest import ManifestNonValido


def _manifest(**dip):
    return types.SimpleNamespace(slug="iem", dipendenze=dip)


@pytest.fixture
def immagine(monkeypatch):
    """Un'immagine finta: numpy 2.5.4 e i pacchetti Debian elencati, dpkg-query presente."""
    python = {"numpy": "2.5.4", "opencv-python-headless": "4.14.0.94"}
    debian = {"tesseract-ocr", "libglib2.0-0t64"}

    def versione(nome):
        if nome not in python:
            raise importlib.metadata.PackageNotFoundError(nome)
        return python[nome]
    monkeypatch.setattr(dipendenze.importlib.metadata, "version", versione)
    monkeypatch.setattr(dipendenze, "_dpkg_installato", lambda p: p in debian)
    monkeypatch.setattr(dipendenze.shutil, "which", lambda cmd: "/usr/bin/" + cmd)
    return types.SimpleNamespace(python=python, debian=debian)


def test_manifest_con_dipendenze_valide(addons_tmp):
    m = manifest.leggi(addons_tmp.crea("iem", dipendenze={"python": ["numpy>=2.0", "xlwt"], "sistema": ["tesseract-ocr"]}))
    assert m.dipendenze == {"python": ["numpy>=2.0", "xlwt"], "sistema": ["tesseract-ocr"]}
    assert manifest.leggi(addons_tmp.crea("alfa")).dipendenze == {}


@pytest.mark.parametrize("valore, atteso", [
    (["numpy"], "atteso un dizionario"),
    ({"pip": ["numpy"]}, "chiavi sconosciute: pip"),
    ({"python": "numpy"}, "python deve essere una lista"),
    ({"python": ["numpy==2.0"]}, "'numpy==2.0' non valido"),          # solo nome o nome>=versione
    ({"python": ["numpy; rm -rf /"]}, "non valido"),
    ({"sistema": ["Tesseract OCR"]}, "sistema: 'Tesseract OCR' non valido"),
])
def test_manifest_con_dipendenze_sbagliate(addons_tmp, valore, atteso):
    with pytest.raises(ManifestNonValido) as exc:
        manifest.leggi(addons_tmp.crea("iem", dipendenze=valore))
    assert atteso in str(exc.value)


def test_niente_manca(immagine):
    assert dipendenze.mancanti(_manifest(python=["numpy>=2.0", "opencv-python-headless"],
                                         sistema=["tesseract-ocr"])) == []
    assert dipendenze.mancanti(_manifest()) == []


def test_mancano_python_e_sistema(immagine):
    assert dipendenze.mancanti(_manifest(python=["numpy", "PyMuPDF"], sistema=["tesseract-ocr", "tesseract-ocr-ita"])) \
        == ["Python PyMuPDF", "sistema tesseract-ocr-ita"]


def test_versione_minima(immagine):
    assert dipendenze.mancanti(_manifest(python=["numpy>=2.5.4"])) == []
    assert dipendenze.mancanti(_manifest(python=["numpy>=2.10"])) == ["Python numpy>=2.10"]    # 2.5 < 2.10
    assert dipendenze.mancanti(_manifest(python=["numpy>=3"])) == ["Python numpy>=3"]


def test_suffisso_t64_di_debian(immagine):
    """Su Debian trixie libglib2.0-0 si chiama libglib2.0-0t64: vale anche il nome vecchio."""
    assert dipendenze.mancanti(_manifest(sistema=["libglib2.0-0", "libglib2.0-0t64"])) == []


def test_senza_dpkg_non_blocca(immagine, monkeypatch, caplog):
    monkeypatch.setattr(dipendenze.shutil, "which", lambda cmd: None)
    assert dipendenze.mancanti(_manifest(sistema=["tesseract-ocr-ita"])) == []
    assert "non controllati: tesseract-ocr-ita" in caplog.text


def test_tupla():
    assert dipendenze._tupla("4.14.0.94") == (4, 14, 0, 94)
    assert dipendenze._tupla("2.0rc1") == (2, 0)
    assert dipendenze._tupla("1.3.0.post1") == (1, 3, 0)


def test_dpkg_vero():
    """Sulla macchina dei test: un pacchetto inesistente non risulta installato (se dpkg-query c'è)."""
    if dipendenze.shutil.which("dpkg-query") is None:
        pytest.skip("dpkg-query assente")
    assert not dipendenze._dpkg_installato("pacchetto-che-non-esiste-adabox")
