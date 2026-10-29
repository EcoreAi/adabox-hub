import time
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from ai import motore, strumenti
from ai.gateway import esecuzione, finto
from ai.models import AnelloCatena, Conversazione, Evento, Modello, Profilo, Provider, Turno
from ai.motore import turni
from core.models import Azienda


@pytest.fixture
def scena(db, monkeypatch):
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto", prezzo_input=Decimal("1"),
                                     prezzo_output=Decimal("2"))
    profilo = Profilo.objects.create(nome="Chat", compito="chat", effort="low")
    AnelloCatena.objects.create(profilo=profilo, modello=modello, ordine=1)
    utente = User.objects.create_user("anna", password="x", first_name="Anna")
    conversazione = Conversazione.objects.create(utente=utente, titolo="Prova")
    return {"utente": utente, "conversazione": conversazione, "modello": modello,
            "azienda": Azienda.objects.get(pk=1)}


def _avvia(scena, testo="Che ore sono?"):
    return motore.avvia(scena["conversazione"], testo, scena["utente"], scena["azienda"])


def test_risposta_semplice_con_contesto_e_costo(scena):
    with finto.con_copione([["Ciao ", "Anna!"]]) as chiamate:
        turno = _avvia(scena, "Ciao")
    turno.refresh_from_db()
    assert turno.stato == "completato" and turno.testo == "Ciao Anna!" and turno.modello == scena["modello"]
    assert turno.passi == 1 and turno.costo > 0 and turno.uso["output"] > 0
    domanda = chiamate[0]["messaggi"][0]["testo"]
    assert domanda.startswith("<contesto>") and "Utente: Anna (anna)" in domanda and domanda.endswith("Ciao")
    assert "Data e ora" not in chiamate[0]["sistema"] and chiamate[0]["effort"] == "low"     # sistema stabile
    assert set(chiamate[0]["strumenti"]) >= {"data_e_ora", "app_disponibili"}
    assert [m.ruolo for m in scena["conversazione"].messaggi.all()] == ["utente", "assistente"]
    assert list(Evento.objects.values_list("tipo", flat=True)) == ["utente", "assistente"]


def test_loop_con_strumenti_e_storia_in_sola_aggiunta(scena):
    with finto.con_copione([[("strumento", "data_e_ora", {"fuso": "Europe/Rome"}), ("strumento", "app_disponibili", {})],
                            ["Sono le ", "dieci."]]) as chiamate:
        turno = _avvia(scena)
    turno.refresh_from_db()
    assert turno.stato == "completato" and turno.passi == 2 and turno.testo.endswith("Sono le dieci.")
    assert [e.tipo for e in Evento.objects.all()] == ["utente", "assistente", "strumento", "assistente"]
    risultati = Evento.objects.get(tipo="strumento").dati["risultati"]
    assert [r["errore"] for r in risultati] == [False, False] and '"giorno"' in risultati[0]["contenuto"]
    secondo = chiamate[1]["messaggi"]
    assert secondo[:3] == chiamate[0]["messaggi"] + [secondo[1], secondo[2]]       # la storia cresce soltanto
    assert secondo[2]["ruolo"] == "strumento" and len(secondo[2]["risultati"]) == 2
    assert any(v.get("fatti") for v in turno.avanzamento)


def test_strumento_inesistente_o_in_errore(scena):
    def esplode(contesto, **kw):
        raise ValueError("database irraggiungibile")
    strumenti.registra(strumenti.Strumento("esplode", "test", {"type": "object", "properties": {}}, esplode))
    try:
        with finto.con_copione([[("strumento", "inventato", {}), ("strumento", "esplode", {})], ["Non ci riesco."]]):
            turno = _avvia(scena)
    finally:
        strumenti.registro._registro.pop("esplode")
    risultati = Evento.objects.get(tipo="strumento").dati["risultati"]
    assert risultati[0]["errore"] and "inesistente" in risultati[0]["contenuto"]
    assert risultati[1]["errore"] and "database irraggiungibile" in risultati[1]["contenuto"]
    turno.refresh_from_db()
    assert turno.stato == "completato"


def test_strumenti_con_permesso_e_timeout(scena, monkeypatch, settings):
    settings.AI_STRUMENTI_SINCRONI = False                  # il timeout c'è solo con il thread
    lento = strumenti.Strumento("lento", "test", {"type": "object", "properties": {}},
                                lambda c: time.sleep(2) or "fatto", timeout=0.2)
    riservato = strumenti.Strumento("riservato", "test", {"type": "object", "properties": {}}, lambda c: "segreto",
                                    permesso="core.delete_azienda")
    for s in (lento, riservato):
        strumenti.registra(s)
    try:
        nomi = [s.nome for s in strumenti.disponibili(scena["utente"])]
        assert "lento" in nomi and "riservato" not in nomi
        with finto.con_copione([[("strumento", "lento", {}), ("strumento", "riservato", {})], ["ok"]]):
            _avvia(scena)
    finally:
        for s in (lento, riservato):
            strumenti.registro._registro.pop(s.nome)
    risultati = Evento.objects.get(tipo="strumento").dati["risultati"]
    assert "superato" in risultati[0]["contenuto"] and "non permesso" in risultati[1]["contenuto"]


def test_budget_di_passi(scena, monkeypatch):
    monkeypatch.setattr(turni, "MAX_PASSI", 3)
    with finto.con_copione([[("strumento", "data_e_ora", {})]] * 3):
        turno = _avvia(scena)
    turno.refresh_from_db()
    assert turno.stato == "completato" and turno.passi == 3 and "troppi passi" in turno.testo
    assert Evento.objects.last().tipo == "strumento"                         # storia valida


def test_budget_di_costo(scena, monkeypatch):
    monkeypatch.setattr(turni, "MAX_COSTO", Decimal("0"))
    with finto.con_copione([[("strumento", "data_e_ora", {})], ["non arriva"]]):
        turno = _avvia(scena)
    turno.refresh_from_db()
    assert "spesa massima" in turno.testo and turno.passi == 1


def test_errore_del_modello_con_storia_valida(scena):
    with finto.con_copione([[("errore", "AUTENTICAZIONE")]]):
        turno = _avvia(scena)
    turno.refresh_from_db()
    assert turno.stato == "errore" and "chiave API" in turno.testo
    assert scena["conversazione"].messaggi.last().ruolo == "assistente"


def test_senza_configurazione(scena):
    Profilo.objects.all().delete()
    turno = _avvia(scena)
    turno.refresh_from_db()
    assert turno.stato == "errore" and "configura l'assistente" in turno.testo


def test_stop_durante_la_risposta(scena):
    def ferma_e_continua(messaggi):
        Turno.objects.update(richiesta_stop=True)
        return ["primo pezzo ", "secondo"]
    with finto.con_copione([ferma_e_continua]):
        turno = _avvia(scena)
    turno.refresh_from_db()
    assert turno.stato == "fermato" and "interrotta" in turno.testo
    assert Evento.objects.last().tipo == "assistente"


def test_turno_senza_battito_diventa_interrotto(scena):
    from datetime import timedelta

    from django.utils import timezone
    conversazione = scena["conversazione"]
    vecchio = Turno.objects.create(conversazione=conversazione, utente=scena["utente"])
    Turno.objects.filter(pk=vecchio.pk).update(battito=timezone.now() - timedelta(minutes=5))
    Evento.objects.create(conversazione=conversazione, turno=vecchio, tipo="assistente", dati={
        "ruolo": "assistente", "blocchi": [{"tipo": "strumento", "id": "x1", "nome": "data_e_ora", "argomenti": {}}]})
    with finto.con_copione([["ripartito"]]) as chiamate:
        nuovo = _avvia(scena)
    vecchio.refresh_from_db()
    assert vecchio.stato == "interrotto" and nuovo.pk != vecchio.pk
    sintetico = Evento.objects.filter(tipo="strumento").get()
    assert "ESITO SCONOSCIUTO" in sintetico.dati["risultati"][0]["contenuto"]
    assert chiamate[0]["messaggi"][1]["ruolo"] == "strumento"


def test_turno_in_corso_non_si_duplica(scena):
    in_corso = Turno.objects.create(conversazione=scena["conversazione"], utente=scena["utente"])
    assert _avvia(scena).pk == in_corso.pk


def test_fallback_sul_secondo_modello(scena):
    from ai.models import AnelloCatena
    rotto_p = Provider.objects.create(nome="Rotto", tipo="openai_compat", base_url="http://127.0.0.1:9/v1")
    rotto = Modello.objects.create(provider=rotto_p, id_api="x", etichetta="Rotto")
    AnelloCatena.objects.filter(modello=scena["modello"]).update(ordine=2)
    AnelloCatena.objects.create(profilo=Profilo.objects.get(), modello=rotto, ordine=1)
    with finto.con_copione([["dal finto"]]):
        turno = _avvia(scena)
    turno.refresh_from_db()
    assert turno.modello == scena["modello"] and turno.testo == "dal finto"


def test_pagina_chat_usa_il_motore(client, scena):
    client.force_login(scena["utente"])
    from django.contrib.auth.models import Permission
    scena["utente"].user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    c = scena["conversazione"]
    with finto.con_copione([["Risposta vera"]]):
        r = client.post(f"/ai/chat/{c.pk}/invia/", {"testo": "Domanda"}, HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert "Domanda" in html and "Risposta vera" in html
