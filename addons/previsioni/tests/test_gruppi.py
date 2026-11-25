"""La previsione per gruppo (per prodotto, cliente…): tutte le serie in una sola chiamata al servizio."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.utils import timezone

from core.models import Azienda, Lavoro
from core.viste.interroga import richiesta_di
from previsioni import motore, servizio
from previsioni.servizio import ErrorePrevisione


@pytest.fixture
def servizi(monkeypatch):
    chiamate = []

    def chiama(percorso, dati):
        chiamate.append((percorso, dati))
        return {"model": "finto-timestral", "forecasts": [{"id": s["id"], "quantiles": {
            "0.1": [s["values"][-1] - 2 - i for i in range(dati["horizon"])],
            "0.5": [s["values"][-1] + i for i in range(dati["horizon"])],
            "0.9": [s["values"][-1] + 2 + i for i in range(dati["horizon"])]}} for s in dati["series"]]}
    monkeypatch.setattr(servizio, "chiama", chiama)
    return chiamate


def _mese_fa(n):
    return motore.avanti(timezone.localdate().replace(day=1), "mese", -n)


def _lavori(funzione, quanti, mesi):
    for m in mesi:
        for _ in range(quanti):
            lavoro = Lavoro.objects.create(funzione=funzione)
            Lavoro.objects.filter(pk=lavoro.pk).update(creato=timezone.make_aware(
                datetime.datetime.combine(_mese_fa(m).replace(day=10), datetime.time(9))))


@pytest.fixture
def scena(db):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    for i, quanti in enumerate([5, 4, 3, 2, 1]):                       # cinque «prodotti», otto mesi di storia
        _lavori(f"prova.f{i}", quanti, range(1, 9))
    return {"request": richiesta_di(capo, Azienda.objects.get(pk=1))}


def _spec(**altro):
    return {"vista": "core.lavoro", "data": "creato", "misura": "count", "per": "mese", "orizzonte": 3,
            "raggruppa": "funzione", **altro}


def test_primi_tre_prodotti_in_una_chiamata(scena, servizi):
    r = motore.calcola_per_gruppo(_spec(primi=3), scena["request"])
    assert [g["chiave"] for g in r["gruppi"]] == ["prova.f0", "prova.f1", "prova.f2"]   # per totale storico
    assert len(servizi) == 1 and len(servizi[0][1]["series"]) == 3
    assert servizi[0][1]["series"][0]["values"] == [5.0] * 8
    assert r["modello"] == "finto-timestral" and r["esclusi"] == 0
    g = r["gruppi"][0]
    assert len(r["periodi"]) == 3 and [f[0] for f in g["futuro"]] == r["periodi"]
    assert len(g["storico"]) == 8 and g["totale"]["mediana"] == 5 + 6 + 7
    assert g["affidabilita"]["livello"] in ("bassa", "media")        # niente prova sul passato: mai «alta»
    assert len(servizi) == 1                                          # nemmeno il backtest ha chiamato il servizio


def test_gruppo_con_poca_storia_si_esclude(scena, servizi):
    _lavori("prova.nuovo", 9, range(1, 4))                            # solo 3 mesi: sotto MIN_PERIODI
    r = motore.calcola_per_gruppo(_spec(primi=6), scena["request"])
    assert r["esclusi"] == 1
    assert "prova.nuovo" not in [g["chiave"] for g in r["gruppi"]]
    assert len(r["gruppi"]) == 5 and len(servizi) == 1


def test_senza_gruppi_con_storia_si_ferma(scena, servizi):
    with pytest.raises(ErrorePrevisione):
        motore.calcola_per_gruppo(_spec(raggruppa="funzione", filtri={"funzione": "nessuna"}), scena["request"])
    assert not servizi


@pytest.fixture
def ordini(db, client):
    import fiscale
    import prodotti
    from contatti.models import Contatto
    from prodotti.models import Prodotto
    from vendite.models import OrdineVendita, RigaVendita
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("200"))
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", prezzo_vendita=Decimal("10"))
    for m in range(1, 9):
        o = OrdineVendita.objects.create(azienda=azienda, cliente=cliente, data=_mese_fa(m).replace(day=10))
        RigaVendita.objects.create(ordine=o, prodotto=monitor, quantita=Decimal("2"))
        RigaVendita.objects.create(ordine=o, prodotto=cavo, quantita=Decimal("7"))
        o.ricalcola()
        OrdineVendita.objects.filter(pk=o.pk).update(stato=OrdineVendita.CONFERMATO)
    return {"request": richiesta_di(capo, azienda), "monitor": monitor, "cavo": cavo}


def test_misura_aziendale_per_prodotto(ordini, servizi):
    r = motore.calcola_per_gruppo({"misura_aziendale": "vendite.quantita_venduta", "raggruppa": "prodotto",
                                   "per": "mese", "orizzonte": 2}, ordini["request"])
    assert [g["nome"] for g in r["gruppi"]] == ["Cavo", "Monitor"]
    assert [g["chiave"] for g in r["gruppi"]] == [ordini["cavo"].pk, ordini["monitor"].pk]
    assert len(servizi) == 1
    assert [s["values"] for s in servizi[0][1]["series"]] == [[7.0] * 8, [2.0] * 8]


def test_come_tabella_ha_fascia_e_affidabilita(scena, servizi):
    t = motore.come_tabella(motore.calcola_per_gruppo(_spec(primi=2), scena["request"]))
    assert t["colonne"][0] == "Gruppo" and t["colonne"][-2:] == ["Totale previsto (10–90 %)", "Affidabilità"]
    assert len(t["colonne"]) == 1 + 3 + 3 + 2 and len(t["righe"]) == 2
    riga = t["righe"][0]
    assert len(riga) == len(t["colonne"]) and riga[0] == "prova.f0"
    assert riga[-2] == "18 (6 – 24)" and riga[-1] in ("Bassa", "Media")
