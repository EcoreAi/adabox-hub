"""Funzioni attivabili dei moduli (core.funzioni): manifest, licenza dell'istanza, fonte propria di un modulo."""
import datetime
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.utils import timezone

from core import funzioni, licenza
from core.registry import pacchetti
from core.registry.manifest import ManifestNonValido, valida


def _manifest(**extra):
    return {"name": "Alfa", "version": "1.0.0", "min_core": "1.1", **extra}


def test_il_manifest_dichiara_le_funzioni_e_le_voci_le_nominano(tmp_path):
    m = valida(_manifest(funzioni=[{"chiave": "extra", "label": "Extra", "help": "di più"}],
                         menu=[{"label": "Extra", "url_name": "alfa:extra", "funzione": "extra"}],
                         settings=[{"chiave": "x", "label": "X", "tipo": "booleano", "funzione": "extra"}]), "alfa", tmp_path)
    assert m.funzioni == [{"chiave": "extra", "label": "Extra", "help": "di più"}]
    with pytest.raises(ManifestNonValido, match="funzione 'altra' non dichiarata"):
        valida(_manifest(funzioni=[{"chiave": "extra", "label": "Extra"}],
                         menu=[{"label": "A", "url_name": "alfa:a", "funzione": "altra"}]), "alfa", tmp_path)
    with pytest.raises(ManifestNonValido, match="chiave 'Non Valida'"):
        valida(_manifest(funzioni=[{"chiave": "Non Valida", "label": "X"}]), "alfa", tmp_path)
    with pytest.raises(ManifestNonValido, match="ripetuto"):
        valida(_manifest(funzioni=[{"chiave": "a", "label": "A"}, {"chiave": "a", "label": "B"}]), "alfa", tmp_path)


@pytest.fixture
def chiave(settings):
    privata = Ed25519PrivateKey.generate()
    settings.MODULI_CHIAVI_FIDATE = [pacchetti.pubblica_b64(privata)]
    return privata


def _salva(chiave, **altro):
    scadenza = timezone.localdate() + datetime.timedelta(days=100)
    licenza.salva(json.dumps(licenza.firma({"cliente": "Rossi Srl", "moduli": ["todo", "crm"], "scadenza": scadenza.isoformat(),
                                            "emessa": timezone.now().isoformat(), **altro}, chiave)))


@pytest.mark.django_db
def test_senza_licenza_o_senza_il_modulo_tutte_le_funzioni(chiave):
    assert funzioni.comprese("crm") is None and funzioni.attiva("crm", "qualunque")
    _salva(chiave, funzioni={"crm": ["previsioni", 7], "strano": "non una lista"})
    assert funzioni.comprese("crm") == frozenset({"previsioni"})
    assert funzioni.attiva("crm", "previsioni") and not funzioni.attiva("crm", "punteggio")
    assert funzioni.attiva("todo", "qualunque")             # il modulo non compare: tutte
    assert funzioni.attiva("crm", "")                       # senza chiave: sempre
    assert licenza.attuale().funzioni == {"crm": frozenset({"previsioni"})}   # le voci strane si scartano


@pytest.mark.django_db
def test_un_modulo_con_una_fonte_sua_e_i_template(monkeypatch):
    monkeypatch.setitem(funzioni._fonti, "alfa", lambda: frozenset({"a"}))
    pagina = funzioni.PerPagina()
    assert pagina["alfa"]["a"] and not pagina["alfa"]["b"] and pagina["beta"]["b"]


@pytest.mark.django_db
def test_il_comando_firma_scrive_le_funzioni(chiave, tmp_path):
    import io

    from cryptography.hazmat.primitives import serialization
    from django.core.management import CommandError, call_command
    pem = tmp_path / "k.pem"
    pem.write_bytes(chiave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    uscita = tmp_path / "l.json"
    call_command("licenza", "firma", "--firma", str(pem), "--cliente", "X", "--moduli", "ai,crm", "--scadenza", "2099-01-01",
                 "--funzioni", "ai=memoria, ricerca_web", "--funzioni", "crm=", "--uscita", str(uscita), stdout=io.StringIO())
    assert licenza.leggi(uscita.read_text()).funzioni == {"ai": frozenset({"memoria", "ricerca_web"}), "crm": frozenset()}
    with pytest.raises(CommandError, match="atteso modulo="):
        call_command("licenza", "firma", "--firma", str(pem), "--cliente", "X", "--moduli", "ai", "--scadenza", "2099-01-01",
                     "--funzioni", "memoria", "--uscita", str(uscita), stdout=io.StringIO())
