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


def test_da_ricordare_si_aggiunge_se_il_modello_lo_tace(scena, monkeypatch):
    import json
    from ai.strumenti import registro
    risultato = {"sintesi": "10 appuntamenti nel periodo: 6 già passati, nessuno in corso, 4 da venire.",
                 "da_ricordare": {"testo": "Ne sono già passati 6 nel periodo: vuoi sentirli?", "segno": 6}, "eventi": []}
    from ai import strumenti as s
    finta = s.Strumento("calendario_agenda", "prova", {"type": "object", "properties": {}}, lambda contesto: risultato)
    monkeypatch.setitem(registro._registro, "calendario_agenda", finta)          # tra gli strumenti della voce
    t, _ = _turno(scena, "Appuntamenti questa settimana?", [[("strumento", "calendario_agenda", {})], ["Hai 4 appuntamenti."]])
    assert t.testo.endswith("Ne sono già passati 6 nel periodo: vuoi sentirli?")
    t, _ = _turno(scena, "E adesso?", [[("strumento", "calendario_agenda", {})], ["Ne hai 4 da fare e sei già fatti stamattina."]])
    assert "vuoi sentirli" not in t.testo                                  # detto in lettere: niente aggiunta
    t, _ = _turno(scena, "E poi?", [[("strumento", "calendario_agenda", {})], ["4 da fare, 6 già passati."]], a_voce=False)
    assert "vuoi sentirli" not in t.testo


def test_calendario_chiede_di_ricordare_solo_se_serve():
    from calendario.ai import da_ricordare
    assert da_ricordare({"passato": 6, "in corso": 0, "da venire": 4})["da_ricordare"]["segno"] == 6
    assert da_ricordare({"passato": 1, "in corso": 0, "da venire": 2})["da_ricordare"]["testo"].startswith("Ne è già passato uno")
    assert da_ricordare({"passato": 0, "in corso": 0, "da venire": 4}) == {}
    assert da_ricordare({"passato": 5, "in corso": 0, "da venire": 0}) == {}            # solo passati: li dice da sé


def test_numeri_da_verificare_senza_falsi_allarmi():
    from ai import provenienza as pv
    def valori(testo):
        return [t for t, _, _ in pv.da_verificare(testo)]
    assert valori("Oggi è lunedì 16 novembre 2026, il 28 ottobre era martedì") == []          # date a parole
    assert valori("Notebook 15 pollici, monitor 27'' 4K, proiettori 500 W, velocità 0,7×") == []  # misure
    assert valori("60.000,00 € oltre IVA (22%)") == ["60.000,00"]                               # l'aliquota no, l'importo sì
    assert valori("margine del 22% sulle vendite") == ["22"]                                    # 22% senza IVA: si controlla
    (t, v, approssimato), = pv.da_verificare("sotto i 22.000 € a gennaio")
    assert approssimato and pv._trovato(v, [pv.Decimal("21004.59")], approssimato)
    assert not pv._trovato(v, [pv.Decimal("21004.59")])                                         # senza «sotto»: no


def test_attivita_pianificate_niente_dati_senza_fonti(scena):
    with finto.con_copione([["Oggi hai fatturato 12.345 euro."], ["Non riesco a leggere il fatturato adesso."], ["Titolo"]]):
        t = motore.avvia(scena["c"], "Riepilogo del fatturato di oggi", scena["u"], compito="pianificate")
    t.refresh_from_db()
    assert t.testo == "Non riesco a leggere il fatturato adesso." and Evento.objects.filter(turno=t, dati__richiamo=True).exists()


def test_domanda_di_seguito_con_dati_letti_prima(scena):
    t1, _ = _turno(scena, "Aziende?", [[("strumento", "cerca_record", {"vista": "core.aziende"})], ["Ecco le aziende."]])
    from ai.models import Evento as Ev
    ev = Ev.objects.filter(turno=t1, tipo=Ev.STRUMENTO).first()
    ev.dati = {"ruolo": "strumento", "risultati": [{"id": "x", "contenuto": '{"totale": 48250.5}', "errore": False}]}
    ev.save()
    t2, _ = _turno(scena, "E il totale?", [["Il totale è 48.250,50 €."]])        # nessuno strumento in questo turno
    assert not Ev.objects.filter(turno=t2, dati__richiamo=True).exists() and "48.250,50" in t2.testo
    assert t2.provenienza["esito"] == "verificato"


def test_i_codici_dei_documenti_non_sono_cifre_da_verificare():
    from ai import guardia
    assert guardia.CIFRE.findall("Il preventivo PV/2026/0002 e l'ordine S00012 di [S00012](/vendite/ordini/12/)") == []
    assert guardia.CIFRE.findall("alle 13:30 per 1.250,50 €") == ["13:30", "1.250,50"]
