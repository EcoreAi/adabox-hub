import json
import sys

import pytest
from django.contrib.auth.models import Group
from django.db import connection

from core import backup
from core.management.commands import modulo_applica as applica
from core.models import Modulo
from core.registry import install, manifest, reload
from core.registry.manifest import ManifestNonValido


@pytest.fixture
def ambiente(addons_tmp, settings, tmp_path, monkeypatch, db):
    settings.BACKUP_DIR = tmp_path / "backup"
    if connection.vendor == "postgresql":          # pg_dump c'è nell'immagine Docker, non sull'host dei test
        monkeypatch.setattr(backup, "_postgres", lambda dest, db: dest.write_bytes(b""))
    chiamate = []

    def finto(operazione, slugs, **opzioni):
        chiamate.append((operazione, list(slugs), opzioni, stato(addons_tmp)))
    monkeypatch.setattr(install, "_applica", finto)
    addons_tmp.chiamate = chiamate
    return addons_tmp


def stato(addons_tmp):
    p = addons_tmp.dir / "installed.json"
    return json.loads(p.read_text())["installed"] if p.exists() else None


def backups(settings):
    return sorted(p.name for p in settings.BACKUP_DIR.iterdir()) if settings.BACKUP_DIR.exists() else []


def _crm(ambiente):
    ambiente.crea("contatti")
    ambiente.crea("crm", depends=["contatti"])


def test_installa_con_dipendenze_confermate(ambiente, settings):
    _crm(ambiente)
    chieste = []
    piano = install.installa(["crm"], conferma=lambda extra: chieste.append(extra) or True)
    assert piano == ["contatti", "crm"] and chieste == [["contatti"]]
    assert stato(ambiente) == ["contatti", "crm"]
    assert len(backups(settings)) == 1 and "pre-installa-contatti-crm" in backups(settings)[0]
    assert ambiente.chiamate == [("installa", ["contatti", "crm"], {"demo": False}, ["contatti", "crm"])]


def test_installa_dipendenze_rifiutate(ambiente, settings):
    _crm(ambiente)
    assert install.installa(["crm"], conferma=lambda extra: False) == []
    assert stato(ambiente) is None and backups(settings) == [] and ambiente.chiamate == []


def test_gia_installato(ambiente, settings):
    ambiente.crea("alfa")
    install.scrivi_stato(["alfa"])
    with pytest.raises(install.GiaInstallato):
        install.installa(["alfa"])
    assert backups(settings) == []


def test_min_core_troppo_alta(ambiente, settings):
    ambiente.crea("alfa", min_core="9.0")
    with pytest.raises(ManifestNonValido):
        install.installa(["alfa"])
    assert backups(settings) == []


def test_applica_fallita_ripristina(ambiente, monkeypatch):
    ambiente.crea("alfa")
    ambiente.crea("beta")
    install.scrivi_stato(["alfa"])

    def esplode(*a, **k):
        raise install.ApplicaFallita("boom")
    monkeypatch.setattr(install, "_applica", esplode)
    with pytest.raises(install.ApplicaFallita):
        install.installa(["beta"])
    assert stato(ambiente) == ["alfa"]
    riga = Modulo.objects.get(slug="beta")
    assert riga.stato == Modulo.ERRORE and "boom" in riga.ultimo_errore


def test_backup_fallito(ambiente, monkeypatch):
    ambiente.crea("alfa")

    def fallisce(motivo):
        raise backup.BackupFallito("disco pieno")
    monkeypatch.setattr(backup, "esegui", fallisce)
    with pytest.raises(backup.BackupFallito):
        install.installa(["alfa"])
    assert stato(ambiente) is None and ambiente.chiamate == []


def test_scrivi_stato_atomica(ambiente):
    install.scrivi_stato(["alfa", "beta"])
    assert [p.name for p in ambiente.dir.iterdir() if "installed" in p.name] == ["installed.json"]
    assert json.loads((ambiente.dir / "installed.json").read_text()) == {"schema": 1, "installed": ["alfa", "beta"]}


def test_disinstalla_con_dipendenti(ambiente):
    _crm(ambiente)
    install.scrivi_stato(["contatti", "crm"])
    with pytest.raises(install.DipendentiInstallati) as exc:
        install.disinstalla("contatti")
    assert "crm" in str(exc.value)


def test_disinstalla_applica_prima_dello_stato(ambiente):
    _crm(ambiente)
    install.scrivi_stato(["contatti", "crm"])
    install.disinstalla("crm")
    assert ambiente.chiamate == [("disinstalla", ["crm"], {"elimina_dati": False}, ["contatti", "crm"])]
    assert stato(ambiente) == ["contatti"]


@pytest.mark.django_db(transaction=True)  # sincronizza scrive prima del backup: vedi core/backup.py
def test_aggiorna(ambiente, settings):
    ambiente.crea("crm", version="1.1.0")
    install.scrivi_stato(["crm"])
    Modulo.objects.create(slug="crm", nome="Crm", versione_installata="1.0.0")
    assert install.aggiorna(["crm"]) == ["crm"]
    assert ambiente.chiamate[0][:3] == ("aggiorna", ["crm"], {})
    assert any("pre-aggiorna-crm" in b for b in backups(settings))


def test_niente_da_aggiornare(ambiente):
    ambiente.crea("crm")
    install.scrivi_stato(["crm"])
    Modulo.objects.create(slug="crm", nome="Crm", versione_installata="1.0.0")
    with pytest.raises(install.NienteDaAggiornare):
        install.aggiorna(["crm"])


def test_riavvia_solo_se_riuscito(ambiente, monkeypatch):
    ambiente.crea("alfa")
    ambiente.crea("beta")
    ricariche = []
    monkeypatch.setattr(reload, "richiedi", lambda: ricariche.append(1) or True)
    install.installa(["alfa"], riavvia=True)
    assert ricariche == [1]
    monkeypatch.setattr(install, "_applica", lambda *a, **k: (_ for _ in ()).throw(install.ApplicaFallita("x")))
    with pytest.raises(install.ApplicaFallita):
        install.installa(["beta"], riavvia=True)
    assert ricariche == [1]


# --- funzioni di supporto di modulo_applica (il flusso completo è testato con todo) ---

def test_carica_fixture(ambiente, monkeypatch):
    cartella = ambiente.crea("alfa")
    (cartella / "data").mkdir()
    for f in ("base.json", "demo.json"):
        (cartella / "data" / f).write_text("[]")
    m = manifest.leggi(cartella)
    m.data, m.demo = ["data/base.json"], ["data/demo.json"]
    chiamate = []
    monkeypatch.setattr(applica, "call_command", lambda *a, **k: chiamate.append(a))
    applica.carica_fixture(m, demo=False)
    applica.carica_fixture(m, demo=True)
    assert chiamate == [("loaddata", str(cartella / "data/base.json")),
                        ("loaddata", str(cartella / "data/base.json"), str(cartella / "data/demo.json"))]


def test_esegui_hook(ambiente):
    cartella = ambiente.crea("hookprova", hooks="hookprova.hooks")
    (cartella / "hooks.py").write_text(
        "chiamate = []\n\ndef post_upgrade(modulo, da):\n    chiamate.append((modulo, da))\n")
    m = manifest.leggi(cartella)
    try:
        assert applica.esegui_hook(m, "post_upgrade", "riga", "0.9.0") is True
        assert sys.modules["hookprova.hooks"].chiamate == [("riga", "0.9.0")]
        assert applica.esegui_hook(m, "post_install", "riga") is False
    finally:
        for nome in [n for n in sys.modules if n.startswith("hookprova")]:
            del sys.modules[nome]


def test_aggiorna_riga(ambiente):
    m = manifest.leggi(ambiente.crea("alfa", application=True))
    riga = applica.aggiorna_riga(m, stato=Modulo.INSTALLATO, versione_installata="1.0.0", gruppi_creati=["G"])
    assert (riga.nome, riga.stato, riga.versione_disponibile, riga.application, riga.gruppi_creati) == (
        "Alfa", Modulo.INSTALLATO, "1.0.0", True, ["G"])


def test_disinstalla_rimuove_i_gruppi(ambiente):
    ambiente.crea("alfa")
    Group.objects.create(name="Alfa / Utente")
    Modulo.objects.create(slug="alfa", nome="Alfa", stato=Modulo.INSTALLATO, gruppi_creati=["Alfa / Utente"])
    applica.Command()._disinstalla("alfa", elimina_dati=False)
    assert not Group.objects.filter(name="Alfa / Utente").exists()
    assert Modulo.objects.get(slug="alfa").stato == Modulo.DISPONIBILE
