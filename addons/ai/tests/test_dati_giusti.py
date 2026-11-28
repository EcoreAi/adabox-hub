"""Risposte sbagliate che venivano dagli strumenti, non dal modello (revisione del 27/11/2026).

- A voce mancava lo strumento delle misure: «Parla con Ada» sommava le fatture a mano, bozze comprese, e dava un
  fatturato diverso da quello della chat (597.781,71 € contro 579.830,91 € il 19/11).
- L'agenda elencava come «tuoi» gli appuntamenti di tutti i colleghi che l'utente vede, e oltre i 200 contava i primi 200.
- Tabelle e grafici con più di 100 gruppi tagliavano i primi 100 in ordine di nome e solo dopo ordinavano per valore: il
  gruppo più grande poteva non esserci; per giorno restavano i giorni più vecchi.
- «Che attività ho da fare?» finiva sul calendario: niente diceva al modello dove stanno le attività."""
import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from ai import artifact, motore, strumenti
from ai.gateway import finto
from ai.models import Conversazione
from ai.strumenti import viste
from ai.tests.test_chat_gruppo2 import _chat, s  # noqa: F401  (fixture)
from core.models import Azienda


@pytest.fixture
def capo(db):
    """Un utente che vede tutto, con il suo contesto per gli strumenti."""
    utente = User.objects.create_superuser("capo", "capo@example.com", "x", first_name="Carla")
    azienda = Azienda.objects.get(pk=1)
    return {"u": utente, "az": azienda, "ctx": strumenti.Contesto(
        utente=utente, azienda=azienda, conversazione=Conversazione.objects.create(utente=utente, titolo="x", titolo_generato=True))}


# ---------- a voce ----------

def test_a_voce_ada_ha_lo_strumento_delle_misure(s):
    with finto.con_copione([["Ecco."]]) as chiamate:
        motore.avvia(_chat(s), "Quanto abbiamo fatturato?", s["u"], s["az"])
        scritta = chiamate[0]["strumenti"]                               # la prima chiamata: dopo c'è quella del titolo
    with finto.con_copione([["Ecco."]]) as chiamate:
        motore.avvia(_chat(s), "Quanto abbiamo fatturato?", s["u"], s["az"], voce=True)
        a_voce = chiamate[0]["strumenti"]
    assert "misura" in scritta and "grafico" in scritta
    assert "misura" in a_voce and "grafico" not in a_voce              # a voce restano fuori solo gli strumenti da vedere


# ---------- agenda ----------

def _evento(azienda, titolo, tra_ore, organizzatore, partecipanti=()):
    from calendario.models import Evento
    inizio = timezone.now() + datetime.timedelta(hours=tra_ore)
    evento = Evento.objects.create(azienda=azienda, titolo=titolo, inizio=inizio, fine=inizio + datetime.timedelta(hours=1),
                                   organizzatore=organizzatore)
    evento.partecipanti.set(partecipanti)
    return evento


def test_l_agenda_di_default_e_quella_di_chi_chiede(capo):
    from calendario.ai import agenda
    luca = User.objects.create_user("luca", first_name="Luca", last_name="Bianchi")
    _evento(capo["az"], "Organizzo io", 1, capo["u"])
    _evento(capo["az"], "Mi hanno invitata", 2, luca, [capo["u"]])
    _evento(capo["az"], "Riunione di Luca", 3, luca)
    domani = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
    miei = agenda(capo["ctx"], a=domani)
    assert [e["titolo"] for e in miei["eventi"]] == ["Organizzo io", "Mi hanno invitata"]
    assert miei["di"] == "miei" and sum(miei["conteggio"].values()) == 2 and "2 appuntamenti" in miei["sintesi"]
    assert miei["eventi"][1]["organizzatore"] == "Luca Bianchi"
    tutti = agenda(capo["ctx"], a=domani, di="tutti")
    assert [e["titolo"] for e in tutti["eventi"]] == ["Organizzo io", "Mi hanno invitata", "Riunione di Luca"]
    assert tutti["di"] == "tutti" and [e["tuo"] for e in tutti["eventi"]] == [True, True, False]
    with pytest.raises(strumenti.ErroreStrumento, match="miei"):
        agenda(capo["ctx"], di="di Luca")


def test_l_agenda_conta_tutti_gli_appuntamenti_anche_oltre_quelli_che_elenca(capo, monkeypatch):
    import calendario.ai as modulo
    monkeypatch.setattr(modulo, "MAX_EVENTI", 3)
    for n in range(5):
        _evento(capo["az"], f"Appuntamento {n}", n + 1, capo["u"])
    domani = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
    r = modulo.agenda(capo["ctx"], a=domani)
    assert len(r["eventi"]) == 3 and sum(r["conteggio"].values()) == 5
    assert r["sintesi"].startswith("5 appuntamenti") and "primi 3 di 5" in r["nota"]


# ---------- più di 100 gruppi ----------

@pytest.fixture
def tante_citta(capo):
    """120 città con un contatto e una, l'ultima in ordine alfabetico, con sette."""
    from contatti.models import Contatto
    Contatto.objects.bulk_create([Contatto(azienda=capo["az"], nome=f"Contatto {i}", citta=f"Borgo {i:03d}") for i in range(1, 121)]
                                 + [Contatto(azienda=capo["az"], nome=f"Zeta {i}", citta="Zagarolo") for i in range(7)])
    return capo


def test_la_tabella_per_gruppo_mette_in_testa_il_gruppo_piu_grande_anche_oltre_cento(tante_citta):
    r = artifact.tabella(tante_citta["ctx"], vista="contatti.contatti", per="citta", misura="count", titolo="Contatti per città")
    dati = artifact.Artifact.objects.get(pk=r["artifact"]).dati
    assert dati["righe"][0] == ["Zagarolo", 7] and dati["totale"] == 121


def test_il_grafico_per_gruppo_tiene_i_piu_grandi_anche_oltre_cento(tante_citta):
    r = artifact.grafico(tante_citta["ctx"], vista="contatti.contatti", per="citta", tipo="barre")
    assert r["serie"][0] == ["Zagarolo", 7] or tuple(r["serie"][0]) == ("Zagarolo", 7)
    assert sum(v for _, v in r["serie"]) == r["totale"] == 127            # le barre, con «Altro», fanno il totale


def test_il_grafico_di_analisi_tiene_i_piu_grandi_anche_oltre_cento(tante_citta):
    from core.viste import interroga
    r = interroga.calcola({"vista": "contatti.contatti", "per": "citta"}, interroga.richiesta_di(tante_citta["u"], tante_citta["az"]))
    assert ("Zagarolo", 7) in [tuple(p) for p in r["serie"]] and sum(v for _, v in r["serie"]) == r["totale"] == 127


def test_per_giorno_restano_i_giorni_piu_recenti(capo):
    from calendario.models import Evento
    oggi = timezone.now().replace(hour=9, minute=0, second=0, microsecond=0)
    Evento.objects.bulk_create([Evento(azienda=capo["az"], titolo=f"Giorno {n}", inizio=oggi - datetime.timedelta(days=n),
                                       fine=oggi - datetime.timedelta(days=n) + datetime.timedelta(hours=1),
                                       organizzatore=capo["u"]) for n in range(150)])
    tutti = viste.aggrega_record(capo["ctx"], vista="calendario.eventi", per="inizio:giorno", ordina="inizio")["gruppi"]
    assert len(tutti) == 150
    grafico = artifact.grafico(capo["ctx"], vista="calendario.eventi", per="inizio:giorno", tipo="linee")
    assert grafico["serie"][-1][0] == tutti[-1]["gruppo"]                 # l'ultimo punto è oggi, non cento giorni dopo l'inizio
    senza_ordine = viste.aggrega_record(capo["ctx"], vista="calendario.eventi", per="inizio:giorno")
    assert len(senza_ordine["gruppi"]) == 100 and senza_ordine["gruppi"][-1]["gruppo"] == tutti[-1]["gruppo"]
    assert "ultimi 100" in senza_ordine["nota"]


def test_oltre_cento_gruppi_la_nota_dice_che_non_e_una_classifica(tante_citta):
    r = viste.aggrega_record(tante_citta["ctx"], vista="contatti.contatti", per="citta")
    assert len(r["gruppi"]) == 100 and r["totale"] == 127
    assert "in ordine di nome" in r["nota"] and "«primi»" in r["nota"]
    primo = viste.aggrega_record(tante_citta["ctx"], vista="contatti.contatti", per="citta", primi=1)
    assert primo["gruppi"] == [{"gruppo": "Zagarolo", "valore": 7}]


# ---------- attività da fare ----------

def test_ada_sa_dove_stanno_le_attivita_da_fare(capo):
    """«Che attività ho da fare?» riceveva gli appuntamenti: nelle domande d'oro del 27/11 lo facevano tutti e due i
    modelli. La vista delle attività ora si presenta, e lo strumento dell'agenda dice che cosa non è."""
    elenco = {v["vista"]: v for v in viste.elenco_viste(capo["ctx"])}
    descrizione = elenco["todo.attivita"]["contiene"].lower()
    assert all(parola in descrizione for parola in ("da fare", "compiti", "assegnatario"))
    agenda = {x.nome: x for x in strumenti.disponibili(capo["u"])}["calendario_agenda"]
    assert "non le attività da fare" in agenda.descrizione and "di=\"tutti\"" in agenda.descrizione


# ---------- quantità ----------

def test_una_quantita_con_tre_decimali_non_sembra_un_migliaio():
    """La quantità 7 arrivava al modello come «7.000», che in italiano si legge settemila."""
    from decimal import Decimal

    from vendite.models import RigaVendita
    quantita, sconto = RigaVendita._meta.get_field("quantita"), RigaVendita._meta.get_field("sconto")
    riga = RigaVendita(quantita=Decimal("7.000"), sconto=Decimal("12.50"))
    assert viste.valore(riga, quantita) == "7" and viste.valore(riga, sconto) == "12.50"         # i due decimali restano
    for scritta, attesa in (("1.500", "1.5"), ("0.125", "0.125"), ("100.000", "100"), ("12.340", "12.34")):
        riga.quantita = Decimal(scritta)
        assert viste.valore(riga, quantita) == attesa
