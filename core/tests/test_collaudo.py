import shutil

import pytest
from django.core.management import CommandError, call_command

from core.registry import collaudo


def _modulo(addons_tmp, slug, test, **extra):
    cartella = addons_tmp.crea(slug, **extra)
    shutil.rmtree(cartella / "migrations")                     # nessun modello: niente migrazioni
    (cartella / "tests").mkdir()
    (cartella / "tests" / "__init__.py").write_text("")
    (cartella / "tests" / f"test_{slug}.py").write_text(test)
    return cartella


@pytest.mark.slow
def test_collaudo_buono_e_cattivo(addons_tmp, capsys):
    _modulo(addons_tmp, "buono", "def test_ok():\n    assert 1 + 1 == 2\n")
    _modulo(addons_tmp, "dipendente", "def test_ok():\n    import buono\n", depends=["buono"])
    _modulo(addons_tmp, "cattivo", "def test_ko():\n    assert False, 'rotto apposta'\n")
    ordine, info = collaudo.da_collaudare()
    assert ordine.index("buono") < ordine.index("dipendente")
    risultati = {s: collaudo.collauda(s, info) for s in ordine}
    assert risultati["buono"].ok and [p for p, _ in risultati["buono"].passi] == ["migrate", "installa", "test", "disinstalla"]
    assert risultati["dipendente"].ok                          # la dipendenza è copiata nell'istanza
    assert not risultati["cattivo"].ok and risultati["cattivo"].passi[-1] == ("test", False)
    assert "rotto apposta" in risultati["cattivo"].dettaglio
    with pytest.raises(CommandError, match="cattivo"):
        call_command("modulo", "collauda", "--tutti")
    assert "Collaudo di buono… OK" in capsys.readouterr().out


def test_moduli_sconosciuti(addons_tmp):
    with pytest.raises(ValueError, match="fantasma"):
        collaudo.da_collaudare(["fantasma"])
