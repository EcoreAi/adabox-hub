"""Il piano: date da capacità, ferie e dipendenze, nessuna scrittura, solo ciò che l'utente può vedere."""
import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

import progetti
from capacita import piano
from capacita.models import Capacita
from core.models import Azienda
from personale.models import Assenza, Dipendente, TipoAssenza
from progetti.models import Compito, FaseCompito, Milestone, Progetto
from timesheet.models import RigaOre

LUN = datetime.date(2026, 6, 8)


@pytest.fixture
def s(db):
    call_command("loaddata", str(Path(progetti.__file__).parent / "data/fasi.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    anna = User.objects.create_user("anna", "anna@example.com", "x")
    luca = User.objects.create_user("luca", "luca@example.com", "x")
    Capacita.objects.create(azienda=azienda, utente=anna, ore_giorno=8, quota=100)
    Capacita.objects.create(azienda=azienda, utente=luca, ore_giorno=8, quota=100)
    return {"az": azienda, "anna": anna, "luca": luca, "p": Progetto.objects.create(azienda=azienda, nome="Portale", fine=datetime.date(2026, 6, 12))}


def _c(s, titolo, ore, chi=("anna",), **extra):
    c = Compito.objects.create(azienda=s["az"], progetto=extra.pop("progetto", s["p"]), titolo=titolo, ore_previste=D(ore), **extra)
    c.assegnatari.set([s[n] for n in chi])
    return c


def _date(s, oggi=LUN):
    return {v.titolo: (v.inizio, v.fine) for v in piano.calcola(s["az"], oggi).voci}


def test_festivi():
    assert piano.pasqua(2026) == datetime.date(2026, 4, 5) and piano.pasqua(2027) == datetime.date(2027, 3, 28)
    assert piano.festivo(datetime.date(2026, 4, 6)) and piano.festivo(datetime.date(2026, 6, 2)) and not piano.festivo(LUN)


def test_coda_per_priorita_e_scadenza(s):
    _c(s, "Normale", 8)
    _c(s, "Urgente", 8, scadenza=LUN + datetime.timedelta(days=30))
    _c(s, "Alta", 8, priorita="alta")
    d = _date(s)
    assert d["Alta"][1] == LUN and d["Urgente"][1] == LUN + datetime.timedelta(days=1) and d["Normale"][1] == LUN + datetime.timedelta(days=2)


def test_salta_weekend_e_feste(s):
    _c(s, "Lungo", 48)
    assert _date(s)["Lungo"] == (LUN, datetime.date(2026, 6, 15))          # sei giorni, senza sabato e domenica
    assert _date(s, datetime.date(2026, 6, 1))["Lungo"][0] == datetime.date(2026, 6, 1)
    assert _date(s, datetime.date(2026, 6, 1))["Lungo"][1] == datetime.date(2026, 6, 9)      # il 2 giugno non si lavora


def test_quota_e_valori_predefiniti(s):
    Capacita.objects.filter(utente=s["anna"]).update(ore_giorno=8, quota=50)
    _c(s, "Metà", 8)
    assert _date(s)["Metà"][1] == LUN + datetime.timedelta(days=1)
    nuovo = User.objects.create_user("nuovo")
    s["nuovo"] = nuovo
    _c(s, "Senza scheda", D("6.4"), chi=("nuovo",))
    assert _date(s)["Senza scheda"][1] == LUN                                 # 8 h × 80%


def test_ferie_e_permessi_dal_personale(s):
    d = Dipendente.objects.create(azienda=s["az"], nome="Anna", cognome="N", utente=s["anna"])
    t = TipoAssenza.objects.create(nome="Ferie prova") if not TipoAssenza.objects.exists() else TipoAssenza.objects.first()
    Assenza.objects.create(azienda=s["az"], dipendente=d, tipo=t, dal=LUN, al=LUN + datetime.timedelta(days=1), stato=Assenza.APPROVATA)
    Assenza.objects.create(azienda=s["az"], dipendente=d, tipo=t, dal=LUN + datetime.timedelta(days=2), al=LUN + datetime.timedelta(days=2), stato=Assenza.RICHIESTA)
    _c(s, "Dopo le ferie", 8)
    assert _date(s)["Dopo le ferie"] == (LUN + datetime.timedelta(days=2), LUN + datetime.timedelta(days=2))


def test_dipendenze_e_tempo_libero_riusato(s):
    a = _c(s, "Base", 16, chi=("luca",))
    b = _c(s, "Bloccato", 8, priorita="alta")
    b.bloccato_da.add(a)
    _c(s, "Riempie il buco", 8)
    d = _date(s)
    assert d["Bloccato"][0] == LUN + datetime.timedelta(days=2)
    assert d["Riempie il buco"][0] == LUN


def test_blocco_circolare_non_ferma_il_piano(s):
    a, b = _c(s, "A", 8), _c(s, "B", 8)
    a.bloccato_da.add(b)
    b.bloccato_da.add(a)
    assert set(_date(s)) == {"A", "B"}


def test_ore_gia_lavorate_e_compiti_chiusi(s):
    c = _c(s, "Iniziato", 16)
    RigaOre.objects.create(azienda=s["az"], progetto=s["p"], compito=c, utente=s["anna"], ore=D(8), data=LUN)
    _c(s, "Chiuso", 80, fase=FaseCompito.objects.filter(chiusa=True).first())
    d = _date(s)
    assert d["Iniziato"][1] == LUN and "Chiuso" not in d


def test_senza_stima_senza_assegnatario_e_padri(s):
    _c(s, "Senza stima", 0)
    _c(s, "Senza nessuno", 8, chi=())
    padre = _c(s, "Padre", 80)
    _c(s, "Figlio", 8, padre=padre)
    p = piano.calcola(s["az"], LUN)
    assert {v.titolo for v in p.voci} == {"Figlio"}
    assert {v.titolo: v.problema for v in p.senza_data} == {"Senza stima": "Senza stima delle ore", "Senza nessuno": "Senza assegnatario"}


def test_capacita_zero_non_si_blocca(s):
    Capacita.objects.filter(utente=s["anna"]).update(ore_giorno=0)
    _c(s, "Impossibile", 8)
    p = piano.calcola(s["az"], LUN)
    assert not p.voci and "due anni" in p.senza_data[0].problema


def test_piu_assegnatari_dividono(s):
    _c(s, "Coppia", 16, chi=("anna", "luca"))
    assert _date(s)["Coppia"] == (LUN, LUN)


def test_consegna_del_progetto_e_ritardo(s):
    _c(s, "Lungo", 80, scadenza=datetime.date(2026, 6, 12))
    p = piano.calcola(s["az"], LUN)
    c = piano.consegna(p, p.voci, [], s["p"].fine)
    assert c["prevista"] == datetime.date(2026, 6, 19) and c["ritardo"] == 7 and c["in_ritardo"] == 1


def test_carico_e_libera_dal(s):
    _c(s, "Lungo", 48)
    dati = piano.carico(piano.calcola(s["az"], LUN))
    anna = next(r for r in dati["righe"] if r["utente"] == s["anna"])
    assert anna["celle"][0]["percentuale"] == 100 and anna["celle"][1]["percentuale"] == 20
    assert anna["libera_dal"] == datetime.date(2026, 6, 16)


def test_il_piano_non_scrive(s, django_assert_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    _c(s, "Uno", 8)
    with CaptureQueriesContext(connection) as q:
        piano.calcola(s["az"], LUN, piano.Voce(None, "Ipotesi", s["p"].pk, [s["anna"].pk], D(8)))
    assert not [x for x in q if x["sql"].split()[0] in ("INSERT", "UPDATE", "DELETE")]


def test_simulazione_mostra_chi_slitta_e_nessun_compito_nuovo(s, client):
    c = _c(s, "Già in coda", 8, scadenza=datetime.date(2030, 1, 1))
    root = User.objects.create_superuser("root", "r@example.com", "x")
    client.force_login(root)
    r = client.get("/capacita/simula/", {"progetto": s["p"].pk, "persona": s["anna"].pk, "ore": "40", "priorita": "alta"})
    html = r.content.decode()
    assert r.status_code == 200 and "Sarebbe pronto il" in html and "Già in coda" in html
    assert Compito.objects.filter(azienda=s["az"]).count() == 1 and c.pk
    for sbagliato in ({"ore": "NaN"}, {"ore": "abc"}, {"ore": "-1"}, {"ore": "99999"}):
        assert "Scegli progetto" in client.get("/capacita/simula/", {"progetto": s["p"].pk, "persona": s["anna"].pk, **sbagliato}).content.decode()
    assert "Scegli progetto" in client.get("/capacita/simula/", {"progetto": "x", "persona": "y", "ore": "4"}).content.decode()


def test_pagine_permessi_e_dettaglio_progetto(s, client):
    m = Milestone.objects.create(azienda=s["az"], progetto=s["p"], nome="Prima", scadenza=datetime.date(2030, 1, 1))
    _c(s, "Uno", 8, milestone=m)
    _c(s, "Da stimare", 0)
    client.force_login(s["anna"])
    for url in ("consegne", "carico", "gantt", "simula"):
        assert client.get(f"/capacita/{url}/").status_code == 403
    client.force_login(User.objects.create_superuser("root", "r@example.com", "x"))
    html = client.get("/capacita/consegne/").content.decode()
    assert "Portale" in html and "Prima" in html and "Da stimare" in html and "Senza stima delle ore" in html
    assert "Uno" in client.get("/capacita/gantt/").content.decode()
    assert client.get("/capacita/carico/").status_code == 200
    assert "Consegna prevista" in client.get(f"/progetti/progetti/{s['p'].pk}/").content.decode()
