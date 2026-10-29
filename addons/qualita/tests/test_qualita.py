from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command

import progetti
import qualita
from core.models import Azienda
from core.registry import manifest
from core.registry.groups import crea_gruppi
from progetti.models import Compito, FaseCompito, Progetto, Rilascio
from qualita.models import Ambiente, CasoTest, Collaudo, Esecuzione


@pytest.fixture
def scena(db):
    cartella = Path(progetti.__file__).parent
    call_command("loaddata", str(cartella / "data" / "fasi.json"), str(cartella / "data" / "tipi.json"), verbosity=0)
    for app in (progetti, qualita):
        crea_gruppi(manifest.leggi(Path(app.__file__).parent))
    azienda = Azienda.objects.get(pk=1)
    tester = User.objects.create_user("tina", "tina@example.com", "x")
    tester.groups.add(Group.objects.get(name="Qualità / Tester"), Group.objects.get(name="Progetti / Utente"))
    progetto = Progetto.objects.create(azienda=azienda, nome="Gestionale")
    progetto.membri.add(tester)
    rilascio = Rilascio.objects.create(azienda=azienda, progetto=progetto, versione="2.4.0")
    ambiente = Ambiente.objects.create(azienda=azienda, progetto=progetto, nome="Staging",
                                       url="https://staging.example.com", rilascio=rilascio)
    login = CasoTest.objects.create(azienda=azienda, progetto=progetto, area="Accesso", titolo="Login",
                                    passi="Apri la pagina\nInserisci le credenziali\nPremi Entra",
                                    atteso="Si apre la dashboard", priorita=CasoTest.ALTA)
    stampa = CasoTest.objects.create(azienda=azienda, progetto=progetto, area="Ordini", titolo="Stampa ordine",
                                     passi="Apri un ordine\nPremi Stampa", atteso="Si scarica il PDF")
    CasoTest.objects.create(azienda=azienda, progetto=progetto, titolo="Vecchio", passi="x", atteso="y", attivo=False)
    return {"azienda": azienda, "tester": User.objects.get(pk=tester.pk), "progetto": progetto,
            "rilascio": rilascio, "ambiente": ambiente, "login": login, "stampa": stampa}


def test_collaudo_nuovo_con_i_casi_attivi(scena):
    c = Collaudo.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], nome="Collaudo 2.4.0",
                                rilascio=scena["rilascio"], ambiente=scena["ambiente"])
    assert c.esecuzioni.count() == 2 and c.esito() == "in corso"                     # il caso non attivo no
    nuovo = CasoTest.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], titolo="Logout",
                                    passi="Esci", atteso="Torni al login")
    assert c.aggiungi_casi() == 1 and c.aggiungi_casi() == 0
    assert c.esecuzioni.filter(caso=nuovo).exists()


def test_esecuzione_difetto_ed_esito(client, scena):
    c = Collaudo.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], nome="Collaudo 2.4.0",
                                rilascio=scena["rilascio"], ambiente=scena["ambiente"])
    client.force_login(scena["tester"])
    pagina = client.get(f"/qualita/collaudi/{c.pk}/esegui/").content.decode()
    assert "Inserisci le credenziali" in pagina and "Si scarica il PDF" in pagina
    login = c.esecuzioni.get(caso=scena["login"])
    stampa = c.esecuzioni.get(caso=scena["stampa"])
    client.post(f"/qualita/collaudi/{c.pk}/esegui/", {"esecuzione": login.pk, "esito": "superato"})
    client.post(f"/qualita/collaudi/{c.pk}/esegui/", {"esecuzione": stampa.pk, "esito": "fallito",
                                                      "note": "Errore 500"})
    stampa.refresh_from_db()
    assert stampa.eseguito_da == scena["tester"] and c.esito() == "fallito"
    assert c.riepilogo()["percentuale"] == 100
    client.post(f"/qualita/collaudi/{c.pk}/esecuzione/{login.pk}/difetto/")
    assert not Compito.objects.exists()                                             # da un caso superato no
    client.post(f"/qualita/collaudi/{c.pk}/esecuzione/{stampa.pk}/difetto/")
    client.post(f"/qualita/collaudi/{c.pk}/esecuzione/{stampa.pk}/difetto/")
    difetto = Compito.objects.get()
    assert difetto.tipo.difetto and difetto.rilascio == scena["rilascio"] and difetto.progetto == scena["progetto"]
    assert "1. Apri un ordine" in difetto.descrizione and "Errore 500" in difetto.descrizione
    assert "Trovato dal collaudo" in client.get(f"/progetti/compiti/{difetto.pk}/").content.decode()
    html = client.get(f"/progetti/rilasci/{scena['rilascio'].pk}/").content.decode()
    assert "Collaudo 2.4.0" in html and "fallito" in html


def test_collaudo_concluso_non_si_modifica_e_altri_progetti_invisibili(client, scena):
    c = Collaudo.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], nome="C1")
    root = User.objects.create_superuser("root", "r@example.com", "x")
    client.force_login(root)
    client.post(f"/qualita/collaudi/{c.pk}/bottone/concludi/")
    c.refresh_from_db()
    assert c.stato == Collaudo.CONCLUSO
    client.force_login(scena["tester"])
    e = c.esecuzioni.first()
    assert client.post(f"/qualita/collaudi/{c.pk}/esegui/", {"esecuzione": e.pk, "esito": "superato"}).status_code == 403
    segreto = Progetto.objects.create(azienda=scena["azienda"], nome="Segreto")
    altro = Collaudo.objects.create(azienda=scena["azienda"], progetto=segreto, nome="Riservato")
    assert client.get(f"/qualita/collaudi/{altro.pk}/esegui/").status_code == 404
    assert "Riservato" not in client.get("/qualita/collaudi/").content.decode()


def test_viste(client, scena):
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x"))
    for url in ("/qualita/collaudi/", "/qualita/collaudi/kanban/", "/qualita/casi/", "/qualita/ambienti/",
                "/qualita/collaudi/nuovo/"):
        assert client.get(url).status_code == 200, url
    assert Esecuzione.objects.count() == 0
