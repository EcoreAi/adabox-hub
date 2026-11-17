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


def _piu_province():
    for provincia in ("CA", "CA", "CA", "TO"):
        Azienda.objects.create(nome=f"Az {provincia} {Azienda.objects.count()}", provincia=provincia)


def test_aggrega_primi_decrescente(scena):
    _piu_province()                      # MI 2, RM 1, CA 3, TO 1
    from ai.strumenti import viste
    c = strumenti.Contesto(utente=scena["capo"], azienda=scena["azienda"], conversazione=scena["conversazione"])
    r = viste.aggrega_record(c, "core.aziende", per="provincia", ordina="-valore", primi=2)
    assert [(g["gruppo"], g["valore"]) for g in r["gruppi"]] == [("CA", 3), ("MI", 2)]
    assert r["totale"] == 7
    crescente = viste.aggrega_record(c, "core.aziende", per="provincia", ordina="valore")
    assert [g["valore"] for g in crescente["gruppi"]] == [1, 1, 2, 3]


def test_grafico_primi_con_altro(scena):
    _piu_province()
    risultati = _turno(scena, [("grafico", {"vista": "core.aziende", "per": "provincia", "primi": 2})])
    assert not risultati[0]["errore"]
    a = Artifact.objects.get()
    assert a.dati["serie"] == [["CA", 3], ["MI", 2], ["Altro", 2]]
    assert artifact.ricalcola(a)["serie"] == [("CA", 3), ("MI", 2), ("Altro", 2)]


def test_tabella_raggruppata(scena):
    _piu_province()
    risultati = _turno(scena, [("tabella", {"vista": "core.aziende", "per": "provincia", "misura": "count"})])
    assert not risultati[0]["errore"], risultati[0]["contenuto"]
    a = Artifact.objects.get()
    assert len(a.dati["colonne"]) == 2
    assert a.dati["righe"][0] == ["CA", 3] and len(a.dati["righe"]) == 4


def test_argomenti_del_12_novembre(scena):
    """Le tre chiamate fallite del turno 537 (5 clienti in torta): ora sono argomenti validi."""
    _piu_province()
    risultati = _turno(scena, [
        ("aggrega_record", {"vista": "core.aziende", "per": "provincia", "ordina": "-totale", "limite": 2}),
        ("grafico", {"vista": "core.aziende", "per": "provincia", "tipo": "torta", "limite": 2}),
        ("tabella", {"vista": "core.aziende", "per": "provincia", "ordina": "-totale", "limite": 2})])
    assert [r["errore"] for r in risultati] == [False, False, False], [r["contenuto"] for r in risultati]
    assert '"gruppo": "CA"' in risultati[0]["contenuto"] and '"MI"' in risultati[0]["contenuto"]
    assert '"RM"' not in risultati[0]["contenuto"]


def test_primi_anche_nei_grafici_salvati_di_analisi(scena):
    """Un grafico con «primi» salvato in Analisi (stessa spec) si ricalcola con le prime N più «Altro»."""
    from core.viste import interroga
    _piu_province()
    r = interroga.calcola({"vista": "core.aziende", "per": "provincia", "primi": 2},
                          interroga.richiesta_di(scena["capo"], scena["azienda"]))
    assert r["serie"] == [("CA", 3), ("MI", 2), ("Altro", 2)]
    assert r["chiavi"] == ["CA", "MI", None]


def test_primi_veri_oltre_100_gruppi_negli_strumenti(scena):
    """aggrega_record e grafico con «primi» scelgono tra tutti i gruppi, non tra i primi 100 per chiave."""
    from ai.strumenti import viste
    Azienda.objects.bulk_create([Azienda(nome=f"Az {i}", provincia=f"P{i:03d}") for i in range(105)])
    Azienda.objects.create(nome="Az doppia", provincia="P104")
    Azienda.objects.create(nome="Az tripla", provincia="P104")          # 3: più di MI (2) della scena
    c = strumenti.Contesto(utente=scena["capo"], azienda=scena["azienda"], conversazione=scena["conversazione"])
    r = viste.aggrega_record(c, "core.aziende", per="provincia", primi=1)
    assert [(g["gruppo"], g["valore"]) for g in r["gruppi"]] == [("P104", 3)]
    g = artifact.grafico(c, "core.aziende", per="provincia", primi=1)
    assert g["serie"][0] == ("P104", 3)
