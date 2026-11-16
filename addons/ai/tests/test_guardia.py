"""Guardia «dati senza fonti» a voce: una risposta con cifre che non vengono da nessuna parte si rifà una volta; se
resta senza fonti la voce lo dice. Le cifre della domanda, del contesto e degli strumenti non contano."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from ai import motore, voce
from ai.gateway import esecuzione, finto
from ai.models import AnelloCatena, Conversazione, Evento, MessaggioChat, Modello, Profilo, Provider


@pytest.fixture
def scena(db, monkeypatch, settings):
    settings.AI_TURNI_SINCRONI = True
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    m = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto", prezzo_input=Decimal(1), prezzo_output=Decimal(1))
    for compito in ("chat", "titoli"):
        AnelloCatena.objects.create(profilo=Profilo.objects.create(nome=compito, compito=compito), modello=m, ordine=1)
    u = User.objects.create_superuser("anna", "a@example.com", "x", first_name="Anna")
    return {"u": u, "c": Conversazione.objects.create(utente=u, titolo="x")}


def _turno(scena, domanda, copione, a_voce=True):
    with finto.con_copione(copione + [["Titolo"]] * 3) as chiamate:
        t = motore.avvia(scena["c"], domanda, scena["u"], voce=a_voce)
    t.refresh_from_db()
    return t, chiamate


def test_dati_inventati_si_rifanno_e_la_seconda_risposta_vince(scena):
    t, chiamate = _turno(scena, "Che appuntamenti ho oggi?", [
        ["Oggi hai una riunione alle 13:30 e una chiamata alle 15:00."],         # inventato: nessuno strumento
        ["Non ho trovato appuntamenti: non riesco a leggere il calendario."]])
    assert t.testo == "Non ho trovato appuntamenti: non riesco a leggere il calendario."
    assert "13:30" not in t.testo and len([c for c in chiamate if "Titolo" not in str(c)]) >= 2
    richiamo = Evento.objects.get(turno=t, tipo=Evento.UTENTE, dati__richiamo=True)
    assert "13:30" in richiamo.dati["testo"]
    # il richiamo va al modello ma non è un messaggio della chat, e non conta come fonte dei numeri
    assert list(MessaggioChat.objects.filter(conversazione=scena["c"], ruolo="utente").values_list("testo", flat=True)) == ["Che appuntamenti ho oggi?"]
    assert t.provenienza["esito"] == "conversazione"


def test_se_resta_senza_fonti_la_voce_lo_dice(scena):
    t, _ = _turno(scena, "Quanto ho fatturato?", [["Hai fatturato 12.500 euro."], ["Hai fatturato 12.500 euro."]])
    assert t.testo.startswith("Hai fatturato 12.500 euro.") and "non ho trovato questi dati negli strumenti" in t.testo
    assert "verificali" in voce.da_leggere(t.testo)


def test_con_uno_strumento_o_con_le_cifre_della_domanda_niente_richiamo(scena):
    t, _ = _turno(scena, "Che appuntamenti ho?", [
        [("strumento", "app_disponibili", {}), ("strumento", "cerca_record", {"vista": "core.aziende"})],
        ["Hai la riunione delle 13:30."]])
    assert not Evento.objects.filter(turno=t, dati__richiamo=True).exists() and "13:30" in t.testo
    t, _ = _turno(scena, "Ricordami il 15 alle 10:30", [["Va bene, il 15 alle 10:30."]])
    assert not Evento.objects.filter(turno=t, dati__richiamo=True).exists()
    t, _ = _turno(scena, "Ciao!", [["Ciao Anna!"]])
    assert t.testo == "Ciao Anna!"


def test_la_chat_scritta_non_cambia(scena):
    t, _ = _turno(scena, "Che appuntamenti ho oggi?", [["Riunione alle 13:30."]], a_voce=False)
    assert t.testo == "Riunione alle 13:30." and not Evento.objects.filter(turno=t, dati__richiamo=True).exists()


def test_cifre_pronunciabili_ed_emoji():
    assert voce.per_la_voce("Alle 13:30 e alle 9:00") == "Alle 13 e 30 e alle 9"
    assert voce.per_la_voce("Totale 1.250,50 €, poi € 80") == "Totale 1250 euro e 50, poi 80 euro"
    assert voce.per_la_voce("Scade il 16/11/2026") == "Scade il 16 novembre 2026"
    assert voce.per_la_voce("Margine 12,5%") == "Margine 12 virgola 5 per cento"
    assert voce.per_la_voce("Ciao Enrico! 👋").strip() == "Ciao Enrico!"
