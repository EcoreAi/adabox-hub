import datetime

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission, User

from ai import strumenti
from ai.markdown import rendi
from ai.models import Conversazione
from ai.strumenti import viste
from core.models import Azienda

con_todo = pytest.mark.skipif("todo" not in settings.ADDONS_ATTIVI, reason="serve l'app todo")


@pytest.fixture
def capo(db):
    return User.objects.create_superuser("capo", "capo@example.com", "x")


@pytest.fixture
def aziende(db):
    prima = Azienda.objects.get(pk=1)
    Azienda.objects.filter(pk=1).update(nome="Alfa Spa", provincia="MI", citta="Milano")
    Azienda.objects.create(nome="Beta Srl", provincia="RM", citta="Roma", attiva=False)
    Azienda.objects.create(nome="Gamma Srl", provincia="MI", citta="Monza")
    prima.refresh_from_db()
    return prima


def _contesto(utente, azienda=None, ambito=""):
    conversazione = Conversazione.objects.create(utente=utente, ambito=ambito)
    return strumenti.Contesto(utente=utente, azienda=azienda, conversazione=conversazione)


def test_elenco_viste_solo_quelle_permesse_e_mai_le_viste_dell_assistente(capo, aziende):
    nomi = [v["vista"] for v in viste.elenco_viste(_contesto(capo, aziende))]
    assert "core.aziende" in nomi and not any(n.startswith("ai.") for n in nomi)
    nessuno = User.objects.create_user("nessuno")
    assert viste.elenco_viste(_contesto(nessuno, aziende)) == "Nessuna vista accessibile."
    nessuno.user_permissions.add(Permission.objects.get(codename="view_azienda"))
    nessuno = User.objects.get(pk=nessuno.pk)
    assert [v["vista"] for v in viste.elenco_viste(_contesto(nessuno, aziende))] == ["core.aziende"]


def test_chat_limitata_a_un_app_vede_solo_le_sue_viste(capo, aziende):
    assert viste.elenco_viste(_contesto(capo, aziende, ambito="inesistente")) == "Nessuna vista accessibile."
    with pytest.raises(strumenti.ErroreStrumento, match="inesistente o non accessibile"):
        viste.cerca_record(_contesto(capo, aziende, ambito="inesistente"), "core.aziende")


def test_descrivi_vista(capo, aziende):
    d = viste.descrivi_vista(_contesto(capo, aziende), "core.aziende")
    campi = {c["nome"]: c for c in d["campi"]}
    assert campi["nome"]["modificabile"] and campi["nome"]["obbligatorio"] and campi["nome"]["tipo"] == "testo"
    assert campi["attiva"]["tipo"] == "sì/no" and "obbligatorio" not in campi["attiva"]
    assert d["permessi"] == {"crea": True, "modifica": True, "elimina": True}
    assert d["bottoni_del_record"] == [{"nome": "attiva", "etichetta": "Attiva", "rischio": "scrittura"}]
    assert d["azioni_su_piu_record"] == [{"nome": "disattiva", "etichetta": "Disattiva"}]
    assert d["ricerca_libera_su"] == ["nome", "partita_iva"]


def test_cerca_con_testo_filtri_ordine_e_pagine(capo, aziende):
    c = _contesto(capo, aziende)
    r = viste.cerca_record(c, "core.aziende", filtri={"provincia": "MI"}, ordina="-nome")
    assert [x["nome"] for x in r["risultati"]] == ["Gamma Srl", "Alfa Spa"] and r["totale"] == 2
    assert set(r["risultati"][0]) == {"id", "nome", "url", "partita_iva", "citta", "attiva"}
    assert r["risultati"][0]["url"] == f"/core/aziende/{r['risultati'][0]['id']}/"
    assert viste.cerca_record(c, "core.aziende", testo="beta")["risultati"][0]["attiva"] is False
    r = viste.cerca_record(c, "core.aziende", filtri='{"nome__in": ["Alfa Spa", "Beta Srl"]}', limite=1,
                           campi=["citta"])
    assert r["totale"] == 2 and len(r["risultati"]) == 1 and "pagina 2" in r["nota"]
    assert set(r["risultati"][0]) == {"id", "nome", "url", "citta"}
    assert viste.cerca_record(c, "core.aziende", filtri={"nome__in": ["Alfa Spa"]}, pagina=2)["risultati"] == []


@pytest.mark.parametrize("argomenti, errore", [
    ({"filtri": {"inventato": 1}}, "non ha il campo"),
    ({"filtri": {"nome__in": "Alfa"}}, "lista"),
    ({"filtri": {"nome__regex": "A"}}, "non è una relazione"),
    ({"filtri": {"a__b__c": 1}}, "al massimo un salto"),
    ({"filtri": {"nome__nome": 1}}, "non è una relazione"),
    ({"filtri": "non è JSON"}, "oggetto JSON"),
    ({"ordina": "inventato"}, "non ha il campo"),
    ({"campi": ["inventato"]}, "non leggibili"),
    ({"limite": "molti"}, "numeri interi"),
])
def test_cerca_rifiuta_argomenti_non_validi(capo, aziende, argomenti, errore):
    with pytest.raises(strumenti.ErroreStrumento, match=errore):
        viste.cerca_record(_contesto(capo, aziende), "core.aziende", **argomenti)


def test_campi_sensibili_esclusi(capo, aziende):
    utenti = viste.vista_per(_contesto(capo, aziende), "core.profili") if any(
        v["vista"] == "core.profili" for v in viste.elenco_viste(_contesto(capo, aziende))) else None
    for v in viste.viste(_contesto(capo, aziende)):
        assert not any(viste.SENSIBILE.search(f.name) for f in viste.campi_leggibili(v)), v
    assert utenti is None or "password" not in [f.name for f in viste.campi_leggibili(utenti)]
    with pytest.raises(strumenti.ErroreStrumento):
        viste._percorso(viste.vista_per(_contesto(capo, aziende), "core.aziende"), "chatter__password")


def test_leggi_record(capo, aziende):
    c = _contesto(capo, aziende)
    beta = Azienda.objects.get(nome="Beta Srl")
    r = viste.leggi_record(c, "core.aziende", beta.pk)
    assert r["nome"] == "Beta Srl" and r["citta"] == "Roma" and r["attiva"] is False
    assert r["bottoni_disponibili"] == [{"nome": "attiva", "etichetta": "Attiva"}]
    with pytest.raises(strumenti.ErroreStrumento, match="non trovato"):
        viste.leggi_record(c, "core.aziende", 9999)


def test_aggrega_conteggi_per_gruppo(capo, aziende):
    c = _contesto(capo, aziende)
    r = viste.aggrega_record(c, "core.aziende", per="provincia")
    assert r["totale"] == 3 and {g["gruppo"]: g["valore"] for g in r["gruppi"]} == {"MI": 2, "RM": 1}
    assert viste.aggrega_record(c, "core.aziende", filtri={"attiva": True})["totale"] == 2
    assert viste.aggrega_record(c, "core.aziende", per="attiva")["gruppi"] == [
        {"gruppo": "no", "valore": 1}, {"gruppo": "sì", "valore": 2}]
    with pytest.raises(strumenti.ErroreStrumento, match="numerico"):
        viste.aggrega_record(c, "core.aziende", misura="sum:nome")
    with pytest.raises(strumenti.ErroreStrumento, match="solo per i campi data"):
        viste.aggrega_record(c, "core.aziende", per="nome:mese")


@con_todo
def test_dati_di_un_altra_azienda_invisibili_e_somme_per_mese(capo, aziende):
    from todo.models import Attivita
    beta = Azienda.objects.get(nome="Beta Srl")
    Attivita.objects.create(azienda=aziende, titolo="Chiamare Rossi", scadenza=datetime.date(2026, 10, 3),
                            assegnatario=capo)
    Attivita.objects.create(azienda=aziende, titolo="Offerta Rossi", scadenza=datetime.date(2026, 11, 5))
    Attivita.objects.create(azienda=beta, titolo="Segreta di Beta", scadenza=datetime.date(2026, 10, 9))
    c = _contesto(capo, aziende)
    r = viste.cerca_record(c, "todo.attivita", filtri={"scadenza__gte": "2026-10-01"})
    assert sorted(x["nome"] for x in r["risultati"]) == ["Chiamare Rossi", "Offerta Rossi"]
    assert r["scelte"]["stato"]["aperta"] and r["risultati"][0]["stato"] == "aperta"
    assert viste.cerca_record(c, "todo.attivita", filtri={"assegnatario__username": "capo"})["totale"] == 1
    mesi = viste.aggrega_record(c, "todo.attivita", per="scadenza:mese")["gruppi"]
    assert mesi == [{"gruppo": "ottobre 2026", "valore": 1}, {"gruppo": "novembre 2026", "valore": 1}]
    altra = Attivita.objects.get(titolo="Segreta di Beta")
    with pytest.raises(strumenti.ErroreStrumento, match="non trovato"):
        viste.leggi_record(c, "todo.attivita", altra.pk)
    limitata = _contesto(capo, aziende, ambito="todo")
    assert {v["app"] for v in viste.elenco_viste(limitata)} == {"todo"}


def test_strumenti_registrati_e_risultato_nel_log(capo, aziende, settings):
    from ai.gateway import finto
    from ai.models import AnelloCatena, Evento, Modello, Profilo, Provider
    from ai import motore
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)
    conversazione = Conversazione.objects.create(utente=capo)
    with finto.con_copione([[("strumento", "aggrega_record", {"vista": "core.aziende", "per": "provincia"})],
                            ["Due a Milano."]]) as chiamate:
        turno = motore.avvia(conversazione, "Quante aziende per provincia?", capo, aziende)
    turno.refresh_from_db()
    assert {"elenco_viste", "descrivi_vista", "cerca_record", "leggi_record", "aggrega_record"} <= set(
        chiamate[0]["strumenti"])
    risultato = Evento.objects.get(tipo="strumento").dati["risultati"][0]
    assert not risultato["errore"] and '"MI"' in risultato["contenuto"] and turno.testo == "Due a Milano."


def test_link_interni_nelle_risposte():
    html = rendi("Vedi [l'ordine](/vendite/ordini/3/) e [fuori](//evil.example/x) e [js](javascript:alert(1))")
    assert '<a href="/vendite/ordini/3/" target="_blank"' in html
    assert 'href="//evil' not in html and 'href="javascript' not in html
