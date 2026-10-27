import os

import pytest
from django.core.management import CommandError, call_command

import core
from core.registry import manifest
from core.registry.manifest import ManifestNonValido, core_compatibile


def _errori(addons_tmp, slug="alfa", **extra):
    cartella = addons_tmp.crea(slug, **extra)
    with pytest.raises(ManifestNonValido) as exc:
        manifest.leggi(cartella)
    return str(exc.value)


def test_manifest_minimo_valido(addons_tmp):
    m = manifest.leggi(addons_tmp.crea("alfa"))
    assert (m.slug, m.name, m.version) == ("alfa", "Alfa", "1.0.0")
    assert m.depends == []
    assert m.application is False


def test_chiave_sconosciuta(addons_tmp):
    assert "nome" in _errori(addons_tmp, nome="x")


def test_manca_min_core(addons_tmp):
    cartella = addons_tmp.crea("alfa")
    (cartella / "__manifest__.py").write_text(repr({"name": "Alfa", "version": "1.0.0"}))
    with pytest.raises(ManifestNonValido) as exc:
        manifest.leggi(cartella)
    assert "min_core" in str(exc.value)


def test_versione_non_semver(addons_tmp):
    assert "X.Y.Z" in _errori(addons_tmp, version="1.0")


def test_min_core_troppo_alta(addons_tmp):
    msg = _errori(addons_tmp, min_core="9.0")
    assert "9.0" in msg and core.__version__ in msg


def test_slug_riservato(addons_tmp):
    assert "riservato" in _errori(addons_tmp, slug="admin")


def test_slug_non_valido(addons_tmp):
    assert "Alfa-1" in _errori(addons_tmp, slug="Alfa-1")


def test_dipendenza_non_valida(addons_tmp):
    assert "Alfa" in _errori(addons_tmp, depends=["Alfa"])


def test_gruppi_validi(addons_tmp):
    m = manifest.leggi(addons_tmp.crea("alfa", groups={"G": ["todo.view_x", "todo.*"]}))
    assert m.groups == {"G": ["todo.view_x", "todo.*"]}


def test_gruppi_permesso_senza_app(addons_tmp):
    assert "view_x" in _errori(addons_tmp, groups={"G": ["view_x"]})


def test_menu_senza_url_name(addons_tmp):
    assert "url_name" in _errori(addons_tmp, menu=[{"label": "A"}])


def test_menu_permesso_con_asterisco(addons_tmp):
    msg = _errori(addons_tmp, menu=[{"label": "A", "url_name": "alfa:x", "permission": "alfa.*"}])
    assert "permission" in msg


def test_data_file_assente(addons_tmp):
    assert "data/x.json" in _errori(addons_tmp, data=["data/x.json"])


def test_data_file_presente(addons_tmp):
    cartella = addons_tmp.crea("alfa", data=["data/x.json"])
    (cartella / "data").mkdir()
    (cartella / "data" / "x.json").write_text("[]")
    assert manifest.leggi(cartella).data == ["data/x.json"]


def test_manifest_con_codice_non_eseguito(addons_tmp, monkeypatch):
    cartella = addons_tmp.crea("alfa")
    (cartella / "__manifest__.py").write_text("{'name': __import__('os').getcwd()}")

    def esploso():
        raise AssertionError("codice eseguito")
    monkeypatch.setattr(os, "getcwd", esploso)
    with pytest.raises(ManifestNonValido):
        manifest.leggi(cartella)


def test_core_compatibile():
    assert core_compatibile("1.0", "1.4.2")
    assert not core_compatibile("1.5", "1.4.2")
    assert not core_compatibile("1.0", "2.0.0")


def test_comando_verifica_ok(addons_tmp, capsys):
    call_command("modulo", "verifica", str(addons_tmp.crea("alfa")))
    assert "OK alfa 1.0.0" in capsys.readouterr().out


def test_comando_verifica_errore(addons_tmp):
    cartella = addons_tmp.crea("alfa", version="1.0", nome="x")
    with pytest.raises(CommandError) as exc:
        call_command("modulo", "verifica", str(cartella))
    assert "X.Y.Z" in str(exc.value) and "nome" in str(exc.value)


# --- chiavi della fase 2: cron, settings, sequences ---

def test_cron_settings_sequences_validi(addons_tmp):
    m = manifest.leggi(addons_tmp.crea(
        "alfa",
        cron=[{"nome": "Promemoria", "funzione": "alfa.lavori.promemoria", "ogni": "1d", "alle": "07:00"},
              {"nome": "Pulizia", "funzione": "alfa.lavori.pulisci", "ogni": "15m"}],
        settings=[{"chiave": "giorni", "label": "Giorni", "tipo": "intero", "default": 2, "per_azienda": True},
                  {"chiave": "modo", "label": "Modo", "tipo": "scelta", "scelte": [["a", "A"], ["b", "B"]]}],
        sequences=[{"codice": "alfa.ordine", "formato": "ORD/{anno}/{numero:05d}", "azzera": "anno"}]))
    assert len(m.cron) == 2 and m.settings[0]["chiave"] == "giorni" and m.sequences[0]["codice"] == "alfa.ordine"


@pytest.mark.parametrize("voce, atteso", [
    ({"nome": "X", "funzione": "alfa.f", "ogni": "1w"}, "ogni"),
    ({"nome": "X", "funzione": "f", "ogni": "1d"}, "funzione"),
    ({"nome": "X", "funzione": "alfa.f", "ogni": "1h", "alle": "07:00"}, "alle"),
    ({"nome": "X", "funzione": "alfa.f", "ogni": "1d", "alle": "25:00"}, "alle"),
    ({"funzione": "alfa.f", "ogni": "1d"}, "nome"),
    ({"nome": "X", "funzione": "alfa.f", "ogni": "1d", "quando": "x"}, "quando"),
])
def test_cron_non_valido(addons_tmp, voce, atteso):
    assert atteso in _errori(addons_tmp, cron=[voce])


def test_cron_nomi_ripetuti(addons_tmp):
    voce = {"nome": "X", "funzione": "alfa.f", "ogni": "1d"}
    assert "ripetuto" in _errori(addons_tmp, cron=[voce, voce])


@pytest.mark.parametrize("voce, atteso", [
    ({"chiave": "Giorni", "label": "G", "tipo": "intero"}, "chiave"),
    ({"chiave": "g", "label": "G", "tipo": "numero"}, "tipo"),
    ({"chiave": "g", "label": "G", "tipo": "scelta"}, "scelte"),
    ({"chiave": "g", "tipo": "testo"}, "label"),
    ({"chiave": "g", "label": "G", "tipo": "testo", "per_azienda": "si"}, "per_azienda"),
])
def test_settings_non_validi(addons_tmp, voce, atteso):
    assert atteso in _errori(addons_tmp, settings=[voce])


@pytest.mark.parametrize("voce, atteso", [
    ({"codice": "ordine", "formato": "{numero}"}, "codice"),
    ({"codice": "alfa.ordine", "formato": "ORD"}, "numero"),
    ({"codice": "alfa.ordine", "formato": "{numero}", "azzera": "mese"}, "azzera"),
])
def test_sequences_non_valide(addons_tmp, voce, atteso):
    assert atteso in _errori(addons_tmp, sequences=[voce])
