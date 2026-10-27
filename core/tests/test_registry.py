import json

import pytest
from django.core.management import call_command

from core.models import Modulo
from core.registry import modules
from core.registry.manifest import ManifestNonValido


def _stato(addons_tmp, slugs):
    (addons_tmp.dir / "installed.json").write_text(json.dumps({"schema": 1, "installed": slugs}))


def test_scopri(addons_tmp):
    addons_tmp.crea("alfa")
    rotto = addons_tmp.crea("rotto")
    (rotto / "__manifest__.py").write_text("{'name': 1}")
    (addons_tmp.dir / "vuota").mkdir()
    (addons_tmp.dir / "file.txt").write_text("x")
    info = modules.scopri()
    assert sorted(info) == ["alfa", "rotto"]
    assert info["alfa"].manifest.name == "Alfa" and info["alfa"].errore is None
    assert info["rotto"].manifest is None and info["rotto"].errore


def test_ordina_per_dipendenze(addons_tmp):
    addons_tmp.crea("contatti")
    addons_tmp.crea("crm", depends=["contatti"])
    info = modules.scopri()
    assert modules.ordina(["crm", "contatti"], info) == ["contatti", "crm"]


def test_ordina_stabile_per_nome(addons_tmp):
    for s in ("gamma", "alfa", "beta"):
        addons_tmp.crea(s)
    assert modules.ordina(["gamma", "beta", "alfa"], modules.scopri()) == ["alfa", "beta", "gamma"]


def test_ordina_dipendenza_assente(addons_tmp):
    addons_tmp.crea("crm", depends=["contatti"])
    with pytest.raises(ManifestNonValido) as exc:
        modules.ordina(["crm"], modules.scopri())
    assert "contatti" in str(exc.value)


def test_ordina_ciclo(addons_tmp):
    addons_tmp.crea("alfa", depends=["beta"])
    addons_tmp.crea("beta", depends=["alfa"])
    with pytest.raises(ManifestNonValido) as exc:
        modules.ordina(["alfa", "beta"], modules.scopri())
    assert "ciclo" in str(exc.value)


@pytest.mark.django_db
def test_sincronizza_stati(addons_tmp):
    addons_tmp.crea("libero")
    addons_tmp.crea("pari")
    addons_tmp.crea("nuova", version="1.1.0")
    _stato(addons_tmp, ["pari", "nuova", "sparito"])
    Modulo.objects.create(slug="pari", nome="Pari", versione_installata="1.0.0")
    Modulo.objects.create(slug="nuova", nome="Nuova", versione_installata="1.0.0")
    Modulo.objects.create(slug="sparito", nome="Sparito per sempre", versione_installata="1.0.0")
    Modulo.objects.create(slug="vecchio", nome="Vecchio")
    righe = {m.slug: m for m in modules.sincronizza()}
    assert righe["libero"].stato == Modulo.DISPONIBILE and righe["libero"].versione_disponibile == "1.0.0"
    assert righe["pari"].stato == Modulo.INSTALLATO
    assert righe["nuova"].stato == Modulo.DA_AGGIORNARE and righe["nuova"].versione_disponibile == "1.1.0"
    assert righe["sparito"].stato == Modulo.MANCANTE and righe["sparito"].nome == "Sparito per sempre"
    assert "vecchio" not in righe and not Modulo.objects.filter(slug="vecchio").exists()


@pytest.mark.django_db
def test_sincronizza_conserva_errore(addons_tmp):
    addons_tmp.crea("alfa")
    Modulo.objects.create(slug="alfa", nome="Alfa", stato=Modulo.ERRORE, ultimo_errore="boom")
    (riga,) = modules.sincronizza()
    assert riga.stato == Modulo.ERRORE and riga.ultimo_errore == "boom"


@pytest.mark.django_db
def test_comando_lista(addons_tmp, capsys):
    addons_tmp.crea("alfa")
    addons_tmp.crea("beta", version="2.0.0")
    _stato(addons_tmp, ["alfa"])
    call_command("modulo", "lista")
    out = capsys.readouterr().out
    righe = {r.split()[0]: r.split() for r in out.splitlines() if r.split() and r.split()[0] in ("alfa", "beta")}
    assert righe["alfa"][1:] == ["1.0.0", "1.0.0", "installato", "Alfa"]
    assert righe["beta"][1:] == ["—", "2.0.0", "disponibile", "Beta"]
