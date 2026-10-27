import json
from pathlib import Path

from core.registry import bootstrap


def _stato(cartella, slugs):
    (cartella / "installed.json").write_text(json.dumps({"schema": 1, "installed": slugs}))


def _modulo(cartella, slug, manifest="{'name': 'X', 'version': '1.0.0', 'min_core': '1.0'}"):
    (cartella / slug).mkdir()
    (cartella / slug / "__manifest__.py").write_text(manifest)


def test_senza_file_nessun_modulo(tmp_path):
    assert bootstrap.moduli_installati(tmp_path) == []


def test_ordine_conservato(tmp_path):
    _modulo(tmp_path, "beta"); _modulo(tmp_path, "alfa")
    _stato(tmp_path, ["beta", "alfa"])
    assert bootstrap.moduli_installati(tmp_path) == ["beta", "alfa"]


def test_modulo_assente_saltato_con_warning(tmp_path, caplog):
    _modulo(tmp_path, "alfa")
    _stato(tmp_path, ["alfa", "fantasma"])
    assert bootstrap.moduli_installati(tmp_path) == ["alfa"]
    assert "fantasma" in caplog.text


def test_manifest_rotto_saltato(tmp_path, caplog):
    _modulo(tmp_path, "rotto", manifest="{'name': __import__('os')}")
    _stato(tmp_path, ["rotto"])
    assert bootstrap.moduli_installati(tmp_path) == []
    assert "rotto" in caplog.text


def test_forzati_aggiunti_se_presenti(tmp_path):
    _modulo(tmp_path, "alfa"); _modulo(tmp_path, "beta")
    _stato(tmp_path, ["alfa"])
    assert bootstrap.moduli_installati(tmp_path, forzati=["beta", "alfa", "nessuno"]) == ["alfa", "beta"]


def test_schema_sconosciuto(tmp_path):
    (tmp_path / "installed.json").write_text('{"schema": 99, "installed": []}')
    import pytest
    with pytest.raises(ValueError):
        bootstrap.moduli_installati(tmp_path)


def test_non_importa_django():
    sorgente = Path(bootstrap.__file__).read_text()
    assert "django" not in sorgente.lower()
