from pathlib import Path

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import ValidationError
from django.core.management import call_command

import progetti
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi
from progetti.models import Compito, FaseCompito, Progetto

CARTELLA = Path(progetti.__file__).parent


@pytest.fixture
def scena(db):
    call_command("loaddata", str(CARTELLA / "data" / "fasi.json"), verbosity=0)
    crea_gruppi(manifest.leggi(CARTELLA))
    azienda = Azienda.objects.get(pk=1)
    utenti = {}
    for nome in ("capo", "membro", "esterno"):
        u = User.objects.create_user(nome, f"{nome}@example.com", "x")
        u.groups.add(Group.objects.get(name="Progetti / Utente"))
        utenti[nome] = User.objects.get(pk=u.pk)
    sito = Progetto.objects.create(azienda=azienda, nome="Sito", responsabile=utenti["capo"])
    sito.membri.add(utenti["membro"])
    segreto = Progetto.objects.create(azienda=azienda, nome="Segreto", responsabile=utenti["capo"])
    Compito.objects.create(azienda=azienda, progetto=sito, titolo="Home")
    Compito.objects.create(azienda=azienda, progetto=segreto, titolo="Riservato")
    return utenti, sito, segreto


def _titoli(client, url):
    return sorted(str(o) for o, _ in client.get(url).context["righe"])


def test_visibilita_progetti_e_compiti(client, scena):
    utenti, sito, segreto = scena
    client.force_login(utenti["membro"])
    assert _titoli(client, "/progetti/progetti/") == ["Sito"]
    assert _titoli(client, "/progetti/compiti/") == ["Home"]
    assert client.get(f"/progetti/progetti/{segreto.pk}/").status_code == 404
    client.force_login(utenti["esterno"])
    assert _titoli(client, "/progetti/progetti/") == [] and _titoli(client, "/progetti/compiti/") == []
    utenti["esterno"].user_permissions.add(Permission.objects.get(codename="vedi_tutti_progetti"))
    client.force_login(User.objects.get(pk=utenti["esterno"].pk))
    assert _titoli(client, "/progetti/progetti/") == ["Segreto", "Sito"]


def test_compito_assegnato_visibile_anche_fuori_progetto(client, scena):
    utenti, sito, segreto = scena
    riservato = Compito.objects.get(titolo="Riservato")
    riservato.assegnatari.add(utenti["esterno"])
    client.force_login(utenti["esterno"])
    assert _titoli(client, "/progetti/compiti/") == ["Riservato"]


def test_scelte_del_form_compito(client, scena):
    utenti, sito, segreto = scena
    client.force_login(utenti["membro"])
    form = client.get(f"/progetti/compiti/nuovo/?progetto={sito.pk}").context["form"]
    assert list(form.fields["progetto"].queryset) == [sito]
    r = client.post("/progetti/compiti/nuovo/", {"titolo": "Furbo", "progetto": segreto.pk, "fase": 1,
                                                 "priorita": "normale", "ore_previste": "0"})
    assert r.status_code == 200 and not Compito.objects.filter(titolo="Furbo").exists()


def test_padre_dello_stesso_progetto(scena):
    _, sito, segreto = scena
    altro = Compito.objects.get(titolo="Riservato")
    c = Compito(azienda=sito.azienda, progetto=sito, titolo="Figlio", padre=altro)
    with pytest.raises(ValidationError):
        c.full_clean()


def test_sezione_compiti_e_completa(client, scena):
    utenti, sito, _ = scena
    client.force_login(utenti["capo"])
    home = Compito.objects.get(titolo="Home")
    client.post(f"/progetti/compiti/{home.pk}/bottone/completa/")
    home.refresh_from_db()
    assert home.fase.chiusa
    html = client.get(f"/progetti/progetti/{sito.pk}/").content.decode()
    assert "Compiti (1)" in html and "Completati 1 su 1 · 100%" in html


def test_nuovo_progetto_codice_e_responsabile(client, scena):
    utenti, _, _ = scena
    capo = utenti["capo"]
    capo.user_permissions.add(Permission.objects.get(codename="add_progetto"))
    client.force_login(User.objects.get(pk=capo.pk))
    client.post("/progetti/progetti/nuovo/", {"nome": "Nuovo", "stato": "attivo"})
    p = Progetto.objects.get(nome="Nuovo")
    assert p.codice == "PRJ/0001" and p.responsabile == capo


def test_viste(client, scena):
    utenti, _, _ = scena
    client.force_login(utenti["membro"])
    for url in ("/progetti/compiti/kanban/", "/progetti/compiti/calendario/", "/progetti/compiti/grafico/",
                "/progetti/progetti/kanban/"):
        assert client.get(url).status_code == 200, url
