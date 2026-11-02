"""Dalle ore alla fattura: tariffe, monte ore, blocco delle ore, redditività."""
import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command

import fiscale
import helpdesk
import prodotti
from assistenza.models import Contratto, DatiTicket, PoliticaSLA, Supporto
from commesse import operazioni
from commesse.models import Condizioni, CostoOrario, FatturaProgetto, OreFatturate, OreTicket, TariffaPersona
from contatti.models import Contatto
from core import parametri
from core.models import Azienda
from fatturazione import operazioni as fatture
from fatturazione.models import Fattura
from helpdesk.models import Ticket
from progetti.models import Compito, FaseCompito, Progetto
from timesheet.models import RigaOre

GIORNO = datetime.date(2026, 6, 1)


@pytest.fixture
def scena(db):
    for app in (fiscale, prodotti, helpdesk):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", partita_iva="12345678903", cliente=True,
                                      indirizzo="Via Po 2", cap="20100", citta="Milano", provincia="MI")
    capo = User.objects.create_user("capo", "capo@example.com", "x")
    anna = User.objects.create_user("anna", "anna@example.com", "x", first_name="Anna", last_name="Neri")
    luca = User.objects.create_user("luca", "luca@example.com", "x")
    progetto = Progetto.objects.create(azienda=azienda, nome="Portale", cliente=cliente, responsabile=capo)
    condizioni = operazioni.condizioni_di(progetto)
    condizioni.tariffa = D(50)
    condizioni.save()
    TariffaPersona.objects.create(condizioni=condizioni, utente=anna, tariffa=D(80))
    return {"azienda": azienda, "cliente": cliente, "progetto": progetto, "condizioni": condizioni, "anna": anna, "luca": luca, "capo": capo}


def _ore(s, utente, ore, **extra):
    return RigaOre.objects.create(azienda=s["azienda"], progetto=s["progetto"], utente=utente, ore=D(ore), data=GIORNO, **extra)


def _ticket(s):
    t = Ticket.objects.create(azienda=s["azienda"], oggetto="Errore", contatto=s["cliente"])
    DatiTicket.objects.update_or_create(ticket=t, defaults={"progetto": s["progetto"]})
    return t


def test_tariffa_personale_o_del_progetto(scena):
    _ore(scena, scena["anna"], 2)
    _ore(scena, scena["luca"], 3)
    voci = operazioni.da_fatturare(scena["progetto"])
    assert [(v["tariffa"], v["importo"]) for v in voci] == [(D(80), D(160)), (D(50), D(150))]


def test_fattura_raggruppa_blocca_e_non_rifattura(scena, client):
    compito_fase = FaseCompito.objects.first() or FaseCompito.objects.create(nome="Da fare")
    compito = Compito.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], titolo="Login", fase=compito_fase)
    a = _ore(scena, scena["anna"], 2, compito=compito)
    b = _ore(scena, scena["anna"], 1, compito=compito)
    _ore(scena, scena["luca"], 1, fatturabile=False)
    f = operazioni.fattura_ore(scena["progetto"])
    riga = f.righe.get()
    assert riga.quantita == 3 and riga.prezzo == D(80) and "Login" in riga.descrizione and "Anna Neri" in riga.descrizione
    assert f.imponibile == D(240) and f.totale == D("292.80") and f.stato == Fattura.BOZZA
    a.refresh_from_db(); b.refresh_from_db()
    assert a.bloccata and b.bloccata and not a.modificabile
    assert operazioni.da_fatturare(scena["progetto"]) == []
    with pytest.raises(ValidationError, match="Non ci sono"):
        operazioni.fattura_ore(scena["progetto"])


def test_righe_scelte_e_tariffa_mancante(scena):
    a = _ore(scena, scena["anna"], 2)
    b = _ore(scena, scena["luca"], 1)
    f = operazioni.fattura_ore(scena["progetto"], [a.pk])
    b.refresh_from_db()
    assert f.imponibile == D(160) and not b.bloccata
    Condizioni.objects.filter(pk=scena["condizioni"].pk).update(tariffa=0)
    with pytest.raises(ValidationError, match="Manca la tariffa"):
        operazioni.fattura_ore(scena["progetto"])


@pytest.mark.parametrize("come", ["annulla", "elimina", "storna"])
def test_ore_tornano_da_fatturare(scena, come):
    riga = _ore(scena, scena["anna"], 2)
    f = operazioni.fattura_ore(scena["progetto"])
    if come == "annulla":
        f.stato = Fattura.ANNULLATA
        f.save(update_fields=["stato"])
    elif come == "elimina":
        f.delete()
    else:
        fatture.emetti(f)
        nota = fatture.nota_di_credito(f)
        riga.refresh_from_db()
        assert riga.bloccata                                      # la nota in bozza non libera ancora
        fatture.emetti(nota)
    riga.refresh_from_db()
    assert not riga.bloccata and not OreFatturate.objects.exists() and len(operazioni.da_fatturare(scena["progetto"])) == 1


def test_solo_ore_approvate_se_richiesto(scena):
    riga = _ore(scena, scena["anna"], 2)
    parametri.scrivi("commesse.solo_approvate", True, scena["azienda"])
    assert operazioni.da_fatturare(scena["progetto"]) == []
    RigaOre.objects.filter(pk=riga.pk).update(approvata=True)
    assert len(operazioni.da_fatturare(scena["progetto"])) == 1


def test_a_corpo_e_non_fatturabile(scena):
    _ore(scena, scena["anna"], 2)
    scena["condizioni"].tipo, scena["condizioni"].importo_corpo = Condizioni.CORPO, D(5000)
    scena["condizioni"].save()
    assert operazioni.da_fatturare(scena["progetto"]) == []
    f = operazioni.fattura_corpo(scena["progetto"])
    assert f.imponibile == D(5000) and FatturaProgetto.objects.get().progetto == scena["progetto"]


def test_redditivita_con_storia_dei_costi(scena):
    CostoOrario.objects.create(azienda=scena["azienda"], utente=scena["anna"], costo=D(20), dal=datetime.date(2026, 1, 1))
    CostoOrario.objects.create(azienda=scena["azienda"], utente=scena["anna"], costo=D(30), dal=datetime.date(2026, 7, 1))
    _ore(scena, scena["anna"], 10)
    RigaOre.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], utente=scena["anna"], ore=D(2), data=datetime.date(2026, 8, 1), fatturabile=False)
    fatture.emetti(operazioni.fattura_ore(scena["progetto"]))
    r = operazioni.redditivita(scena["progetto"])
    assert r["ore"] == 12 and r["costo"] == D(260) and r["fatturato"] == D(800) and r["in_attesa"] == 0
    assert r["margine"] == D(540) and r["percentuale"] == 67
    _ore(scena, scena["anna"], 1)
    assert operazioni.redditivita(scena["progetto"])["in_attesa"] == D(80)


def test_nota_di_credito_toglie_i_ricavi(scena):
    _ore(scena, scena["anna"], 10)
    f = fatture.emetti(operazioni.fattura_ore(scena["progetto"]))
    fatture.emetti(fatture.nota_di_credito(f))
    r = operazioni.redditivita(scena["progetto"])
    assert r["fatturato"] == 0 and r["in_attesa"] == D(800)


def _contratto(s, ore):
    return Contratto.objects.create(azienda=s["azienda"], nome="Base", cliente=s["cliente"], ore_incluse=D(ore),
                                    politica=PoliticaSLA.objects.create(nome=f"P{ore}"), inizio=datetime.date(2026, 1, 1))


def test_monte_ore_non_fattura_il_compreso_e_fattura_il_resto(scena):
    contratto = _contratto(scena, 5)
    t = _ticket(scena)
    operazioni.registra_su_ticket(t, scena["anna"], D(3), data=GIORNO)
    assert operazioni.da_fatturare(scena["progetto"]) == []
    seconda = operazioni.registra_su_ticket(t, scena["anna"], D(4), data=GIORNO)
    m = operazioni.monte_ore(contratto)
    assert m["usate"] == 7 and m["oltre"] == 2 and m["livello"] == "oltre"
    voci = operazioni.da_fatturare(scena["progetto"])
    assert [(v["riga"].pk, v["ore"], v["importo"]) for v in voci] == [(seconda.pk, D(2), D(160))]
    f = operazioni.fattura_ore(scena["progetto"])
    assert f.imponibile == D(160) and OreFatturate.objects.get().ore == 2


def test_avviso_monte_una_volta_per_soglia(scena):
    contratto = _contratto(scena, 10)
    Supporto.objects.create(azienda=scena["azienda"], progetto=scena["progetto"], contratto=contratto)
    t = _ticket(scena)
    operazioni.registra_su_ticket(t, scena["anna"], D(7), data=GIORNO)
    assert not [m for m in mail.outbox if "Monte ore" in m.subject]
    operazioni.registra_su_ticket(t, scena["anna"], D(1), data=GIORNO)
    operazioni.registra_su_ticket(t, scena["anna"], D("0.5"), data=GIORNO)
    avvisi = [m for m in mail.outbox if "Monte ore" in m.subject]
    assert len(avvisi) == 1 and "80%" in avvisi[0].subject and avvisi[0].to == ["capo@example.com"]
    operazioni.registra_su_ticket(t, scena["anna"], D(2), data=GIORNO)
    assert len([m for m in mail.outbox if "Monte ore" in m.subject]) == 2


def test_ticket_senza_progetto(scena):
    t = Ticket.objects.create(azienda=scena["azienda"], oggetto="Senza")
    with pytest.raises(ValidationError, match="progetto"):
        operazioni.registra_su_ticket(t, scena["anna"], D(1))


def test_pagine(client, superuser, scena):
    t = _ticket(scena)
    _ore(scena, scena["anna"], 2)
    assert client.get(f"/helpdesk/ticket/{t.pk}/").status_code == 200
    r = client.post(f"/commesse/ticket/{t.pk}/ore/", {"ore": "1,5", "descrizione": "Analisi"})
    assert r.status_code == 302 and OreTicket.objects.get().riga.ore == D("1.5")
    assert b"Portale" in client.get("/commesse/da-fatturare/").content
    pagina = client.get(f"/commesse/progetto/{scena['progetto'].pk}/fattura-ore/").content.decode()
    assert "data-ore-form" in pagina
    html = client.get(f"/progetti/progetti/{scena['progetto'].pk}/").content.decode()
    assert "Redditività" in html and "Fattura le ore" in html
    prima = RigaOre.objects.filter(progetto=scena["progetto"]).order_by("pk").first()
    r = client.post(f"/commesse/progetto/{scena['progetto'].pk}/fattura-ore/", {"riga": [prima.pk]})
    f = Fattura.objects.get()
    assert r.url == f"/fatturazione/fatture/{f.pk}/" and f.imponibile == D(160)
    assert client.get(f"/assistenza/contratti/{_contratto(scena, 8).pk}/").status_code == 200


def test_fatture_di_un_altra_azienda_non_si_collegano(client, superuser, scena):
    altra = Azienda.objects.create(nome="Zeta")
    cliente = Contatto.objects.create(azienda=altra, nome="X")
    estranea = Fattura.objects.create(azienda=altra, cliente=cliente)
    r = client.post(f"/commesse/progetto/{scena['progetto'].pk}/collega/", {"fattura": estranea.pk})
    assert r.status_code == 404 and not FatturaProgetto.objects.exists()
