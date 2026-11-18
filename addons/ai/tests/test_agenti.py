import pytest
from django.contrib.auth.models import Group, User
from django.core.management import call_command

from ai import assistenti, motore, valutazione
from ai.gateway import finto
from ai.models import (AnelloCatena, Assistente, Conversazione, Evento, Modello, Profilo, Proposta, Provider, Turno)
from ai.motore import compattazione
from core import cifratura
from core.models import Azienda


@pytest.fixture
def scena(db, client):
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    base = Modello.objects.create(provider=provider, id_api="finto-base", etichetta="Base")
    esperto = Modello.objects.create(provider=provider, id_api="finto-esperto", etichetta="Esperto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=base)
    profilo_esperto = Profilo.objects.create(nome="Esperti", compito="classificazione")
    AnelloCatena.objects.create(profilo=profilo_esperto, modello=esperto)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "client": client, "profilo_esperto": profilo_esperto}


def _avvia(scena, conversazione, testo):
    return motore.avvia(conversazione, testo, scena["capo"], scena["azienda"])


def test_quale_assistente_risponde(scena):
    generale = Assistente.objects.create(nome="Generale", predefinito=True)
    aziende = Assistente.objects.create(nome="Aziende", app="core")
    riservato = Assistente.objects.create(nome="Riservato", app="vendite")
    riservato.gruppi.add(Group.objects.create(name="Commerciali"))
    utente = User.objects.create_user("utente")
    assert assistenti.risolvi(Conversazione(utente=utente), utente) == generale
    assert assistenti.risolvi(Conversazione(utente=utente, ambito="core"), utente) == aziende
    assert assistenti.risolvi(Conversazione(utente=utente, ambito="vendite"), utente) is None    # non nei gruppi
    utente.groups.add(Group.objects.get(name="Commerciali"))
    assert assistenti.risolvi(Conversazione(utente=utente, ambito="vendite"), utente) == riservato
    Assistente.objects.filter(pk=generale.pk).update(attivo=False)
    assert assistenti.risolvi(Conversazione(utente=utente), utente) is None


def test_istruzioni_strumenti_e_modello_dell_assistente(scena):
    Assistente.objects.create(nome="Contabile", predefinito=True, istruzioni="Rispondi sempre in euro.",
                              strumenti=["aggrega_record", "data_e_ora"], profilo=scena["profilo_esperto"])
    with finto.con_copione([["Ok."]]) as chiamate:
        _avvia(scena, Conversazione.objects.create(utente=scena["capo"]), "Ciao")
    assert "Sei l'assistente «Contabile». Istruzioni:\nRispondi sempre in euro." in chiamate[0]["sistema"]
    assert chiamate[0]["strumenti"] == ["aggrega_record", "data_e_ora", "leggi_allegato"] and chiamate[0]["modello"] == "finto-esperto"


def test_esperto_in_sola_lettura_in_una_conversazione_interna(scena):
    Assistente.objects.create(nome="Aziende", app="core", descrizione="anagrafica delle aziende",
                              profilo=scena["profilo_esperto"])
    principale = Conversazione.objects.create(utente=scena["capo"])
    with finto.con_copione([
            [("strumento", "chiedi_esperto", {"esperto": "aziende", "domanda": "Quante aziende attive ci sono?"})],
            [("strumento", "chiedi_esperto", {"esperto": "Aziende", "domanda": "Chiedi a te stesso"})],
            ["Sono 1, risponde l'esperto."],
            ["Secondo l'esperto c'è 1 azienda attiva."]]) as chiamate:
        turno = _avvia(scena, principale, "Chiedi all'esperto delle aziende quante sono attive")
    esperto_chiamata = chiamate[1]
    assert esperto_chiamata["modello"] == "finto-esperto"
    assert "crea_record" not in esperto_chiamata["strumenti"] and "chiedi_esperto" not in esperto_chiamata["strumenti"]
    assert "aggrega_record" in esperto_chiamata["strumenti"]
    risultato = Evento.objects.filter(conversazione=principale, tipo="strumento").first().dati["risultati"][0]
    assert not risultato["errore"] and "Sono 1, risponde l'esperto." in risultato["contenuto"]
    interna = Conversazione.objects.get(nascosta=True)
    assert interna.assistente.nome == "Aziende" and Turno.objects.filter(compito="esperto").count() == 1
    turno.refresh_from_db()
    assert turno.testo == "Secondo l'esperto c'è 1 azienda attiva."
    pagina = scena["client"].get("/ai/chat/").content.decode()
    assert "Esperto: Aziende" not in pagina                                 # le conversazioni interne non si vedono


def test_compattazione_delle_conversazioni_lunghe(scena, monkeypatch):
    conversazione = Conversazione.objects.create(utente=scena["capo"], titolo_generato=True)
    for i in range(3):
        with finto.con_copione([[f"Risposta {i}: " + "dati " * 200]]):
            _avvia(scena, conversazione, f"Domanda {i}")
    monkeypatch.setattr(compattazione, "SOGLIA", 3000)                     # ora la parte conclusa è oltre
    eventi_prima = Evento.objects.filter(conversazione=conversazione).count()
    with finto.con_copione([["## Intento\nCapire i dati.\n## Dati\nRisposte 0-2."], ["Fatto."]]) as chiamate:
        turno = _avvia(scena, conversazione, "Domanda nuova")
    riassunto = Evento.objects.get(tipo="riassunto")
    assert "Domanda 2" in chiamate[0]["messaggi"][0]["testo"] and "## Intento" in chiamate[0]["sistema"]
    messaggi = chiamate[1]["messaggi"]
    assert len(messaggi) == 1 and messaggi[0]["testo"].startswith("<riassunto della conversazione precedente>")
    assert "Risposte 0-2." in messaggi[0]["testo"] and messaggi[0]["testo"].endswith("Domanda nuova")
    assert Evento.objects.filter(conversazione=conversazione).count() == eventi_prima + 3     # utente, riassunto, risp.
    assert riassunto.dati["fino_a"] < Evento.objects.filter(turno=turno, tipo="utente").get().pk
    assert Turno.objects.filter(compito="riassunti", stato="completato").exists()
    with finto.con_copione([["Ancora."]]) as chiamate:                     # sotto soglia: si riparte dal riassunto
        _avvia(scena, conversazione, "Un'altra")
    assert chiamate[0]["messaggi"][0]["testo"].startswith("<riassunto") and len(chiamate[0]["messaggi"]) == 3


def test_valutazione_con_le_domande_d_oro(scena, capsys):
    risultati = valutazione.valuta(valutazione.carica(), scena["capo"], scena["azienda"], copioni=True)
    assert [r["ok"] for r in risultati] == [True] * len(risultati), [r["problemi"] for r in risultati]
    assert not Azienda.objects.filter(nome="Prova valutazione").exists()        # proposte annullate
    assert Proposta.objects.get().stato == "annullata"
    assert not Conversazione.objects.filter(nascosta=False).exists()
    sbagliata = [{"domanda": "Che ore sono?", "strumenti": ["data_e_ora"], "contiene": ["mezzogiorno"],
                  "copione": [["Non lo so."]]}]
    r, = valutazione.valuta(sbagliata, scena["capo"], copioni=True)
    assert not r["ok"] and r["problemi"] == ["strumenti non usati: data_e_ora", "manca «mezzogiorno»"]
    call_command("ai_eval", "--copioni")
    n = len(valutazione.carica())
    assert f"Riuscite {n} su {n}" in capsys.readouterr().out
    Assistente.objects.create(nome="Prova", domande_oro=sbagliata)
    with pytest.raises(SystemExit):
        call_command("ai_eval", "--copioni", "--assistente", "prova")


def test_pagina_degli_assistenti(scena):
    c = scena["client"]
    r = c.post("/ai/assistenti/nuovo/", {"nome": "Vendite", "app": "", "istruzioni": "Sii breve.",
                                         "strumenti": ["cerca_record", "leggi_record"], "domande_oro": "[]",
                                         "attivo": "on"})
    a = Assistente.objects.get()
    assert r.status_code == 302 and a.strumenti == ["cerca_record", "leggi_record"]
    from core.registry import modules
    app = next((s for s, m in modules.manifests_attivi().items() if m.application and s != "ai"), None)
    if app:                                                                 # nel collaudo c'è solo ai
        r = c.post("/ai/assistenti/nuovo/", {"nome": "Doppio", "app": app, "predefinito": "on", "domande_oro": "[]"})
        assert "Solo un assistente generale" in r.content.decode()
    r = c.post("/ai/assistenti/nuovo/", {"nome": "Rotto", "domande_oro": '[{"x": 1}]'})
    assert "almeno &quot;domanda&quot;" in r.content.decode()


def test_con_i_copioni_mai_il_modello_vero(scena):
    """Anche se la catena del server è un modello vero (qui: un provider che esploderebbe), --copioni usa il finto."""
    vero = Provider.objects.create(nome="Vero", tipo="anthropic")
    Modello.objects.filter(provider__nome="Finto").update(provider=vero)            # la chat ora punta al "vero"
    r, = valutazione.valuta([{"domanda": "Che giorno è?", "contiene": ["{oggi_giorno}"],
                              "copione": [["Oggi è {oggi_giorno}."]]}], scena["capo"], copioni=True)
    assert r["ok"] and r["costo"] == 0 and Turno.objects.filter(modello__id_api="finto-valutazione").exists()


def test_con_i_copioni_mai_il_modello_vero_neanche_con_i_livelli(scena, monkeypatch):
    """Con Veloce e Avanzato assegnati Automatico non passa dal profilo: --copioni usa comunque il finto."""
    from ai.gateway import esecuzione
    provati = []
    monkeypatch.setitem(esecuzione.ADATTATORI, "anthropic", lambda modello, *a, **k: provati.append(modello.id_api) or iter(()))
    vero = Provider.objects.create(nome="Vero", tipo="anthropic", chiave_cifrata=cifratura.cifra("k"))
    Modello.objects.create(provider=vero, id_api="vero-veloce", etichetta="Vero veloce", livello_chat=Modello.VELOCE)
    r, = valutazione.valuta([{"domanda": "Che giorno è?", "contiene": ["{oggi_giorno}"],
                              "copione": [["Oggi è {oggi_giorno}."]]}], scena["capo"], copioni=True)
    assert r["ok"] and r["costo"] == 0 and provati == []                     # il vero non è mai stato chiamato


def test_controlla_misura_trova_valore(monkeypatch):
    from types import SimpleNamespace

    from core import misure
    monkeypatch.setattr(misure, "calcola", lambda nome, request, **k: {"valore": 579831.4, "gruppi": []})
    monkeypatch.setattr(valutazione, "_richiesta", lambda utente, azienda: None)
    turno = SimpleNamespace(stato="completato", errore="", provenienza={}, passi=2, testo="Il fatturato è 579.831 €.")
    domanda = {"domanda": "Fatturato?", "misura": {"nome": "fatturazione.fatturato", "periodo": "anno"}}
    assert valutazione.controlla(domanda, turno, ["misura"]) == []
    turno.testo = "Il fatturato è 580.000 €."
    assert valutazione.controlla(domanda, turno, ["misura"]) == ["manca il valore 579.831 (fatturazione.fatturato)"]
    assert valutazione.varianti(579831.4) == ["579.831", "579.831,40"]
    assert valutazione.varianti(3) == ["3"]


def test_controlla_passi_massimi():
    from types import SimpleNamespace
    turno = SimpleNamespace(stato="completato", errore="", provenienza={}, passi=4, testo="Ecco.")
    assert valutazione.controlla({"domanda": "x", "passi_massimi": 2}, turno, []) == ["lenta: 4 passi (massimo 2)"]
    turno.passi = 2
    assert valutazione.controlla({"domanda": "x", "passi_massimi": 2}, turno, []) == []


def test_valuta_riporta_passi_e_valore_nel_copione(scena):
    r, = valutazione.valuta([{"domanda": "Quanto abbiamo fatturato quest'anno?", "strumenti": ["misura"], "passi_massimi": 2,
                              "misura": {"nome": "fatturazione.fatturato", "periodo": "anno"},
                              "copione": [[["strumento", "misura", {"nome": "fatturazione.fatturato", "periodo": "anno"}]],
                                          ["Il fatturato dell'anno è {valore} €."]]}],
                            scena["capo"], scena["azienda"], copioni=True)
    assert r["ok"], r["problemi"]
    assert r["passi"] == 2 and "0 €" in r["risposta"]


def test_solo_modello_porta_la_chiave_del_provider(scena):
    """ai_eval --modello con un modello vero: senza chiave Anthropic dà «Connection error», Mistral «chiave non valida»."""
    from ai import catalogo
    from ai.models import ChiaveAzienda
    provider = Provider.objects.create(nome="Vero", tipo="anthropic", chiave_cifrata=cifratura.cifra("sk-globale"))
    modello = Modello.objects.create(provider=provider, id_api="vero-1", etichetta="Vero")
    profilo = Profilo.objects.get(nome="Chat")
    with valutazione.solo_modello(modello):
        assert catalogo.catena(profilo, scena["azienda"]) == [(modello, "sk-globale")]
        assert catalogo.automatico(profilo, None) == [(modello, "sk-globale")]
    ChiaveAzienda.objects.create(provider=provider, azienda=scena["azienda"], chiave_cifrata=cifratura.cifra("sk-azienda"))
    with valutazione.solo_modello(modello):
        assert catalogo.catena(profilo, scena["azienda"]) == [(modello, "sk-azienda")]


def test_ai_eval_tempi_e_modello(scena, capsys):
    from django.core.management.base import CommandError
    call_command("ai_eval", "--copioni")
    uscita = capsys.readouterr().out
    assert "Tempi: mediana" in uscita and "90%" in uscita and " passi " in uscita
    with pytest.raises(CommandError, match="nessun modello"):
        call_command("ai_eval", "--modello", "non-esiste")
