import pytest
from django.contrib.auth.models import User

from ai import artifact, motore, strumenti
from ai.gateway import finto
from ai.models import AnelloCatena, Artifact, Conversazione, Evento, Modello, Profilo, Provider
from core.models import Azienda


@pytest.fixture
def scena(db, client):
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    Azienda.objects.filter(pk=1).update(nome="Alfa Spa", provincia="MI")
    Azienda.objects.create(nome="Beta Srl", provincia="RM")
    Azienda.objects.create(nome="Gamma Srl", provincia="MI")
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "client": client,
            "conversazione": Conversazione.objects.create(utente=capo, titolo="Prova")}


def _turno(scena, chiamate):
    with finto.con_copione([[("strumento", n, a) for n, a in chiamate], ["Ecco."]]):
        motore.avvia(scena["conversazione"], "Mostrami", scena["capo"], scena["azienda"])
    return Evento.objects.filter(tipo="strumento").last().dati["risultati"]


def test_grafico_con_dati_veri_svg_e_pagina_aggiornata(scena):
    risultati = _turno(scena, [("grafico", {"vista": "core.aziende", "per": "provincia", "tipo": "torta",
                                            "titolo": "Aziende per provincia"}),
                               ("grafico", {"vista": "core.aziende", "per": "provincia", "tipo": "radar"})])
    assert not risultati[0]["errore"] and '"serie": [["MI", 2], ["RM", 1]]' in risultati[0]["contenuto"]
    assert risultati[1]["errore"] and "barre, linee, torta" in risultati[1]["contenuto"]
    a = Artifact.objects.get()
    assert a.tipo == "grafico" and a.dati["serie"] == [["MI", 2], ["RM", 1]] and a.turno_id
    pagina = scena["client"].get(f"/ai/chat/{scena['conversazione'].pk}/").content.decode()
    assert "<svg" in pagina and "Aziende per provincia" in pagina and f"/ai/artifact/{a.pk}/" in pagina

    Azienda.objects.create(nome="Delta", provincia="RM")                     # la pagina usa i dati di oggi
    r = scena["client"].get(f"/ai/artifact/{a.pk}/")
    assert r.status_code == 200 and "<svg" in r.content.decode() and ">2</td>" in r.content.decode()
    csv = scena["client"].get(f"/ai/artifact/{a.pk}/csv/").content.decode("utf-8-sig")
    assert csv.splitlines() == ["Gruppo;Valore", "MI;2", "RM;1"]                 # l'istantanea
    oggi = scena["client"].get(f"/ai/artifact/{a.pk}/csv/?oggi=1").content.decode("utf-8-sig")
    assert "RM;2" in oggi


def test_tabella_con_link_e_salvataggio(scena):
    risultati = _turno(scena, [("tabella", {"vista": "core.aziende", "filtri": {"provincia": "MI"}, "ordina": "nome",
                                            "campi": ["provincia"], "titolo": "Aziende di Milano"})])
    assert '"righe": 2' in risultati[0]["contenuto"]
    a = Artifact.objects.get()
    assert a.dati["colonne"] == ["Azienda", "Provincia"] and a.dati["righe"] == [["Alfa Spa", "MI"],
                                                                                ["Gamma Srl", "MI"]]
    pagina = scena["client"].get(f"/ai/chat/{scena['conversazione'].pk}/").content.decode()
    assert f'href="/core/aziende/{scena["azienda"].pk}/"' in pagina and "Aziende di Milano" in pagina
    r = scena["client"].post(f"/ai/artifact/{a.pk}/salva/", HTTP_HX_REQUEST="true")
    a.refresh_from_db()
    assert r.status_code == 200 and a.salvato and 'aria-pressed="true"' in r.content.decode()
    pagina = scena["client"].get("/ai/chat/").content.decode()
    assert pagina.count("Aziende di Milano") == 1                               # nel pannello dei salvati


def test_artifact_solo_del_proprietario(scena, client):
    _turno(scena, [("tabella", {"vista": "core.aziende"})])
    a = Artifact.objects.get()
    altro = User.objects.create_superuser("altro", "altro@example.com", "x")
    client.force_login(altro)
    for url in (f"/ai/artifact/{a.pk}/", f"/ai/artifact/{a.pk}/csv/"):
        assert client.get(url).status_code == 404
    assert client.post(f"/ai/artifact/{a.pk}/salva/").status_code == 404


def test_grafico_oltre_trenta_categorie_e_errori(scena):
    gruppi = [{"gruppo": f"G{i}", "valore": i} for i in range(40)]
    serie = artifact._serie(gruppi, "cliente")
    assert len(serie) == 30 and serie[0] == ("G39", 39) and serie[-1][0] == "Altro"
    assert artifact._serie(gruppi, "data:mese")[0] == ("G10", 10)
    contesto = strumenti.Contesto(utente=scena["capo"], azienda=scena["azienda"])
    with pytest.raises(strumenti.ErroreStrumento, match="solo in una chat"):
        artifact.grafico(contesto, "core.aziende", "provincia")
