import datetime
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.contrib.auth.models import Permission, User
from django.core import mail
from django.utils import timezone

from ai import motore, pianificate, proposte
from ai.gateway import finto
from ai.models import (AnelloCatena, Conversazione, Evento, MessaggioChat, Modello, Pianificata, Profilo, Proposta,
                       Provider, Turno)
from core import lavori
from core.models import Azienda

ROMA = ZoneInfo("Europe/Rome")
con_discuss = pytest.mark.skipif("discuss" not in settings.ADDONS_ATTIVI, reason="serve l'app discuss")


def _ora(*args):
    return datetime.datetime(*args, tzinfo=ROMA)


@pytest.fixture
def scena(db, client):
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x", first_name="Carla")
    client.force_login(capo)
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "client": client}


def _pianificata(scena, **campi):
    dati = {"utente": scena["capo"], "azienda": scena["azienda"], "nome": "Ordini aperti",
            "istruzioni": "Elenca gli ordini aperti", "ricorrenza": "giorni", "alle": datetime.time(8, 0),
            "giorni": "0", "prossima": timezone.now() - datetime.timedelta(minutes=1), **campi}
    return Pianificata.objects.create(**dati)


@pytest.mark.parametrize("campi, da, attesa", [
    ({"ricorrenza": "giorni", "giorni": "0,1,2,3,4", "alle": datetime.time(8)}, _ora(2026, 10, 30, 9), _ora(2026, 11, 2, 8)),
    ({"ricorrenza": "giorni", "giorni": "0,1,2,3,4", "alle": datetime.time(8)}, _ora(2026, 11, 2, 7), _ora(2026, 11, 2, 8)),
    ({"ricorrenza": "giorni", "giorni": "0", "alle": datetime.time(8)}, _ora(2026, 11, 2, 8), _ora(2026, 11, 9, 8)),
    ({"ricorrenza": "giorni", "giorni": "", "alle": None}, _ora(2026, 11, 2, 9), _ora(2026, 11, 3, 8)),
    ({"ricorrenza": "mese", "giorno_mese": 15, "alle": datetime.time(9)}, _ora(2026, 11, 15, 10), _ora(2026, 12, 15, 9)),
    ({"ricorrenza": "mese", "giorno_mese": 1, "alle": datetime.time(9)}, _ora(2026, 12, 20), _ora(2027, 1, 1, 9)),
    ({"ricorrenza": "ore", "ogni_ore": 3}, _ora(2026, 11, 2, 9), _ora(2026, 11, 2, 12)),
    ({"ricorrenza": "eventi", "minuti_prima": 30}, _ora(2026, 11, 2, 9), _ora(2026, 11, 2, 9, 5)),
])
def test_prossima_esecuzione(campi, da, attesa):
    assert pianificate.calcola_prossima(Pianificata(**campi), da) == attesa


def test_frequenza_in_italiano():
    assert Pianificata(ricorrenza="giorni", giorni="0,1,2,3,4", alle=datetime.time(8)).frequenza() == \
        "dal lunedì al venerdì alle 08:00"
    assert Pianificata(ricorrenza="giorni", giorni="0").frequenza() == "ogni lunedì"
    assert Pianificata(ricorrenza="giorni", giorni="0,2,4").frequenza() == "ogni lunedì, mercoledì e venerdì"
    assert Pianificata(ricorrenza="mese", giorno_mese=1, alle=datetime.time(9)).frequenza() == \
        "il 1 di ogni mese alle 09:00"
    assert Pianificata(ricorrenza="ore", ogni_ore=1).frequenza() == "ogni ora"


def test_creata_dalla_chat_con_conferma(scena):
    conversazione = Conversazione.objects.create(utente=scena["capo"])
    with finto.con_copione([[("strumento", "crea_pianificata", {
            "nome": "Ordini del lunedì", "istruzioni": "Mandami gli ordini aperti sopra 5.000 €", "quando": "giorni",
            "giorni": ["lunedì"], "alle": "08:00"}), ("strumento", "crea_pianificata", {"preset": "riepilogo_mattino"}),
            ("strumento", "crea_pianificata", {"nome": "X", "istruzioni": "Y", "alle": "25:99"})], ["Fatto."]]):
        motore.avvia(conversazione, "Ogni lunedì alle 8 mandami gli ordini aperti", scena["capo"], scena["azienda"])
    risultati = Evento.objects.get(tipo="strumento").dati["risultati"]
    assert risultati[2]["errore"] and "HH:MM" in risultati[2]["contenuto"]
    lunedi, mattino = Proposta.objects.all()
    assert lunedi.titolo == "Pianifica «Ordini del lunedì» ogni lunedì alle 08:00"
    assert {"campo": "Risultato", "dopo": "nella sua chat" + (", in Discuss" if "discuss" in settings.ADDONS_ATTIVI
                                                               else "")} in lunedi.dettagli
    assert not Pianificata.objects.exists()
    proposte.conferma(lunedi, scena["capo"], scena["azienda"])
    proposte.conferma(mattino, scena["capo"], scena["azienda"])
    p, r = Pianificata.objects.get(nome="Ordini del lunedì"), Pianificata.objects.get(nome="Riepilogo del mattino")
    assert p.utente == scena["capo"] and p.elenco_giorni() == [0] and timezone.localtime(p.prossima).weekday() == 0
    assert r.frequenza() == "dal lunedì al venerdì alle 08:00" and "riepilogo" in r.istruzioni


def test_eseguita_dal_worker_una_volta_sola_con_consegna(scena, settings):
    settings.SITO_URL = "https://hub.example.it"
    p = _pianificata(scena, per_email=True, in_discuss=True)
    with finto.con_copione([["Ci sono **2 ordini** aperti: [S00012](/vendite/ordini/12/)."]]) as chiamate:
        assert pianificate.esegui_scadute() == "pianificate eseguite: 1"
        assert pianificate.esegui_scadute() == "pianificate eseguite: 0"          # la prossima è già spostata
    p.refresh_from_db()
    turno = Turno.objects.get()
    assert turno.compito == "pianificate" and turno.stato == "completato" and p.errori == 0
    assert p.prossima > timezone.now() and p.esito.startswith("Eseguita") and p.conversazione.titolo == \
        "Pianificata: Ordini aperti"
    assert "Esecuzione pianificata «Ordini aperti»" in chiamate[0]["messaggi"][0]["testo"]       # al modello
    assert MessaggioChat.objects.filter(ruolo="utente").get().testo == "Elenca gli ordini aperti"   # in chat
    email = mail.outbox[-1]
    assert email.subject == "Ordini aperti" and "S00012 (https://hub.example.it/vendite/ordini/12/)" in email.body
    assert f"https://hub.example.it/ai/chat/{p.conversazione_id}/" in email.body


@con_discuss
def test_consegna_in_discuss_dall_assistente(scena, settings):
    from discuss.models import Messaggio, Notifica
    settings.SITO_URL = "https://hub.example.it"
    _pianificata(scena)
    with finto.con_copione([["Nessun ordine aperto."]]):
        pianificate.esegui_scadute()
    m = Messaggio.objects.get()
    assert m.autore.username == "assistente-ai" and not m.autore.is_active and not m.autore.has_usable_password()
    assert m.corpo.startswith("**Ordini aperti**") and "Nessun ordine aperto." in m.corpo
    assert set(m.canale.membri.all()) == {m.autore, scena["capo"]}
    assert Notifica.objects.get(utente=scena["capo"]).tipo == "diretto"


def test_sospesa_dopo_tre_errori(scena):
    p = _pianificata(scena, in_discuss=False)
    with finto.con_copione([[("errore", "AUTENTICAZIONE")]] * 3):
        for _ in range(3):
            Pianificata.objects.filter(pk=p.pk).update(prossima=timezone.now() - datetime.timedelta(minutes=1))
            pianificate.esegui_scadute()
    p.refresh_from_db()
    assert not p.attiva and p.errori == 3 and p.esito.startswith("Sospesa")
    assert "sospesa" in mail.outbox[-1].subject


def test_pagina_di_gestione(scena, client):
    c = scena["client"]
    r = c.post("/ai/pianificate/nuovo/", {"nome": "Ticket", "istruzioni": "Ticket urgenti", "ricorrenza": "giorni",
                                           "alle": "09:30", "giorni": ["0", "3"], "in_discuss": "on", "attiva": "on"})
    p = Pianificata.objects.get()
    assert r.status_code == 302 and p.utente == scena["capo"] and p.giorni == "0,3"
    assert timezone.localtime(p.prossima).weekday() in (0, 3) and timezone.localtime(p.prossima).hour == 9
    r = c.post("/ai/pianificate/nuovo/", {"nome": "Mese", "istruzioni": "x", "ricorrenza": "mese", "attiva": "on"})
    assert "Indica un giorno da 1 a 28." in r.content.decode()
    with finto.con_copione([["Due ticket urgenti."]]):
        c.post(f"/ai/pianificate/{p.pk}/bottone/esegui_ora/")
    p.refresh_from_db()
    assert p.esito.startswith("Eseguita") and Turno.objects.get().compito == "pianificate"
    assert "Apri la chat dei risultati" in c.get(f"/ai/pianificate/{p.pk}/").content.decode()
    c.post(f"/ai/pianificate/{p.pk}/bottone/sospendi/")
    p.refresh_from_db()
    assert not p.attiva and p.prossima is None
    c.post(f"/ai/pianificate/{p.pk}/bottone/riattiva/")
    p.refresh_from_db()
    assert p.attiva and p.prossima > timezone.now()
    altro = User.objects.create_user("altro", password="x")
    altro.user_permissions.add(Permission.objects.get(codename="view_pianificata"))
    client.force_login(User.objects.get(pk=altro.pk))
    assert client.get(f"/ai/pianificate/{p.pk}/").status_code == 404                  # solo le proprie


def test_controllo_del_worker_nel_manifest():
    from core.registry import modules
    voce = modules.manifests_attivi()["ai"].cron[0]
    assert voce["ogni"] == "1m" and lavori.risolvi(voce["funzione"]) is pianificate.esegui_scadute


@pytest.mark.skipif("calendario" not in settings.ADDONS_ATTIVI, reason="serve l'app calendario")
def test_prima_degli_eventi_una_volta_per_evento(scena):
    from calendario.models import Evento as Appuntamento
    adesso = timezone.now()
    Appuntamento.objects.create(azienda=scena["azienda"], titolo="Riunione Rossi", organizzatore=scena["capo"],
                                inizio=adesso + datetime.timedelta(minutes=20),
                                fine=adesso + datetime.timedelta(minutes=80))
    Appuntamento.objects.create(azienda=scena["azienda"], titolo="Domani", organizzatore=scena["capo"],
                                inizio=adesso + datetime.timedelta(days=1), fine=adesso + datetime.timedelta(days=1,
                                                                                                         hours=1))
    p = _pianificata(scena, ricorrenza="eventi", minuti_prima=30, in_discuss=False,
                     istruzioni="Preparami una scheda del cliente")
    with finto.con_copione([["Scheda pronta."]]) as chiamate:
        pianificate.esegui_scadute()
        Pianificata.objects.filter(pk=p.pk).update(prossima=timezone.now() - datetime.timedelta(minutes=1))
        assert pianificate.esegui_scadute() == "pianificate eseguite: 0"          # stesso evento: non si ripete
    assert len(chiamate) == 1 and "Riunione Rossi" in chiamate[0]["messaggi"][0]["testo"]
