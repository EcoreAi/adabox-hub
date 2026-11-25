"""Il motore di previsione: storia dal database con i permessi di chi guarda, numeri dal servizio, affidabilità con la
prova sul passato, grafico SVG. Spostati da addons/ai/tests/test_specialisti.py quando il motore è uscito
dall'assistente."""
import datetime
import importlib
import json

import pytest
from django.apps import apps
from django.contrib.auth.models import User
from django.utils import timezone

from core import parametri
from core.models import Azienda, Lavoro, Parametro
from core.viste.interroga import richiesta_di
from previsioni import motore, servizio
from previsioni.servizio import ErrorePrevisione


def _finta_risposta(dati):
    """Un Timestral finto: mediana = ultimo valore + 0, +1…; fascia ±2 e qualcosa; gli id tornano come sono arrivati."""
    return {"model": "finto-timestral", "forecasts": [{"id": s["id"], "quantiles": {
        "0.1": [s["values"][-1] - 2 - i for i in range(dati["horizon"])],
        "0.5": [s["values"][-1] + i for i in range(dati["horizon"])],
        "0.9": [s["values"][-1] + 2 + i for i in range(dati["horizon"])]}} for s in dati["series"]]}


@pytest.fixture
def servizi(monkeypatch):
    chiamate = []

    def chiama(percorso, dati):
        chiamate.append((percorso, dati))
        return _finta_risposta(dati)
    monkeypatch.setattr(servizio, "chiama", chiama)
    return chiamate


@pytest.fixture
def scena(db):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    oggi = timezone.localdate().replace(day=15)
    for mesi_fa, quanti in [(8, 2), (7, 3), (6, 3), (5, 4), (4, 4), (3, 5), (2, 5), (1, 6), (0, 9)]:
        mese = motore.avanti(oggi.replace(day=1), "mese", -mesi_fa)
        for _ in range(quanti):
            lavoro = Lavoro.objects.create(funzione="prova.lavoro")
            Lavoro.objects.filter(pk=lavoro.pk).update(creato=timezone.make_aware(
                datetime.datetime.combine(mese.replace(day=10), datetime.time(9))))
    azienda = Azienda.objects.get(pk=1)
    return {"capo": capo, "azienda": azienda, "request": richiesta_di(capo, azienda)}


def _spec(**altro):
    return {"vista": "core.lavoro", "data": "creato", "misura": "count", "per": "mese", "orizzonte": 3, **altro}


def test_periodi():
    assert motore.avanti(datetime.date(2026, 11, 1), "mese", 2) == datetime.date(2027, 1, 1)
    assert motore.avanti(datetime.date(2026, 3, 1), "mese", -3) == datetime.date(2025, 12, 1)
    assert motore.inizio(datetime.date(2026, 10, 29), "settimana") == datetime.date(2026, 10, 26)
    assert motore.etichetta(datetime.date(2026, 10, 1), "mese") == "ott 2026"


def test_previsione_dalla_storia_vera(scena, servizi):
    r = motore.calcola_previsione(_spec(), scena["request"])
    percorso, inviati = servizi[0]
    assert percorso == "/v1/forecast"
    assert inviati["series"][0]["values"] == [2, 3, 3, 4, 4, 5, 5, 6]   # il mese in corso (9) è escluso: incompleto
    assert inviati["horizon"] == 3 and inviati["quantiles"] == [0.1, 0.5, 0.9]
    assert r["futuro"][0] == [motore.etichetta(motore.inizio(timezone.localdate(), "mese"), "mese"), 4.0, 6.0, 8.0]
    assert len(r["storico"]) == 8 and len(r["futuro"]) == 3 and r["modello"] == "finto-timestral"
    disegno = motore.svg_previsione(r, "Lavori previsti")
    assert disegno.startswith("<svg") and "Fascia 10-90 %" in disegno and "stroke-dasharray" in disegno


def test_previsione_rifiuta_storie_corte_e_campi_non_data(scena, servizi):
    with pytest.raises(ErrorePrevisione, match="almeno 6 periodi"):
        motore.calcola_previsione(_spec(filtri={"creato__gte": str(timezone.localdate() - datetime.timedelta(days=100))}),
                                  scena["request"])
    with pytest.raises(ErrorePrevisione, match="non è un campo data"):
        motore.calcola_previsione(_spec(data="funzione"), scena["request"])
    with pytest.raises(ErrorePrevisione, match="non ha il campo"):           # gli errori del kernel restano chiari
        motore.calcola_previsione(_spec(data="inesistente"), scena["request"])
    assert not servizi


def test_la_vista_si_cerca_tra_quelle_dell_utente(scena, servizi):
    with pytest.raises(ErrorePrevisione, match="inesistente o non accessibile"):
        motore.calcola_previsione(_spec(vista="core.nessuna"), scena["request"])
    normale = User.objects.create_user("norma", "n@example.com", "x")
    with pytest.raises(ErrorePrevisione, match="inesistente o non accessibile"):
        motore.vista_accessibile(richiesta_di(normale, scena["azienda"]), "core.lavoro")
    assert motore.vista_accessibile(scena["request"], "core.lavoro").model is Lavoro
    assert not servizi


def test_previsione_mai_negativa_per_serie_positive(monkeypatch):
    monkeypatch.setattr(servizio, "chiama", lambda percorso, dati: {"forecasts": [{"id": "s1", "quantiles": {
        "0.1": [-3.0], "0.5": [1.0], "0.9": [4.0]}}]})
    futuro, _ = motore.prevedi([(None, 1.0)] * 6, 1)
    assert futuro == [(0.0, 1.0, 4.0)]


def test_risposta_del_servizio_non_valida(monkeypatch):
    monkeypatch.setattr(servizio, "chiama", lambda percorso, dati: {"forecasts": [{"id": "altro", "quantiles": {}}]})
    with pytest.raises(ErrorePrevisione, match="non valida"):
        motore.prevedi([(None, 1.0)] * 6, 1)


def test_servizio_giu_messaggio_chiaro(scena, monkeypatch):
    parametri.scrivi("previsioni.url_servizio", "http://127.0.0.1:9")                # porta chiusa
    monkeypatch.setattr(servizio, "TIMEOUT", 2)
    with pytest.raises(ErrorePrevisione, match="non risponde"):
        motore.calcola_previsione(_spec(), scena["request"])


def test_totale_sull_orizzonte_ed_etichette_dell_asse(scena, servizi):
    r = motore.calcola_previsione(_spec(per="settimana", orizzonte=13), scena["request"])
    t = r["totale"]
    assert len(r["futuro"]) == 13 and t["mediana"] == round(sum(f[2] for f in r["futuro"]), 2)
    assert t["basso_10"] <= t["mediana"] <= t["alto_90"]
    disegno = motore.svg_previsione(r, "Lavori per settimana")
    assert disegno.count('transform="rotate(-35') <= 11                     # una decina di etichette, non 40


def test_previsione_dice_l_affidabilita_con_la_prova_sul_passato(scena, servizi):
    a = motore.calcola_previsione(_spec(), scena["request"])["affidabilita"]
    assert a["livello"] == "bassa" and a["periodi_di_storia"] == 8                      # 8 mesi: troppo pochi
    assert a["motivi"][0].startswith("Storia: 8 mesi (per una previsione solida ne servono almeno 24)")
    # con 8 mesi la prova sul passato lascerebbe 5 mesi, sotto il minimo del servizio: si salta
    assert len(servizi) == 1 and a["errore"] is None


def test_prova_sul_passato_con_storia_sufficiente(servizi):
    storia = [(None, float(v)) for v in range(10, 22)]                                 # 12 mesi
    a = motore.affidabilita(storia, [(18.0, 20.0, 22.0)] * 3, 3)
    prova = servizi[0][1]                                              # la stessa previsione senza gli ultimi 3
    assert prova["horizon"] == 3 and prova["series"][0]["values"] == [float(v) for v in range(10, 19)]
    assert a["errore"] is not None and any("già noti" in m for m in a["motivi"])


def test_livelli_di_affidabilita(monkeypatch):
    storia = [(None, 100.0 + i) for i in range(30)]
    monkeypatch.setattr(motore, "prevedi", lambda s, k: ([(v - 5, v, v + 5) for _, v in storia[len(s):len(s) + k]], "finto"))
    alta = motore.affidabilita(storia, [(120.0, 130.0, 140.0)] * 3, 3)
    assert alta["livello"] == "alta" and alta["errore"] == 0.0
    larga = motore.affidabilita(storia, [(0.0, 100.0, 300.0)] * 3, 3)              # intervallo enorme
    assert larga["livello"] == "bassa" and any("±150%" in m for m in larga["motivi"])
    corta = motore.affidabilita(storia[:15], [(120.0, 130.0, 140.0)] * 3, 3)         # 15 mesi: media
    assert corta["livello"] == "media"


def test_prevedi_molte_una_sola_chiamata_con_id_opachi(servizi):
    storie = {"Monitor 27 pollici": [(None, 10.0)] * 6, "Rossi Srl": [(None, 20.0)] * 6, 42: [(None, 30.0)] * 6}
    futuri, modello = motore.prevedi_molte(storie, 2)
    assert len(servizi) == 1 and modello == "finto-timestral"
    percorso, corpo = servizi[0]
    assert percorso == "/v1/forecast" and [s["id"] for s in corpo["series"]] == ["s1", "s2", "s3"]
    testo = json.dumps(corpo)
    assert "Monitor" not in testo and "Rossi" not in testo and "42" not in testo        # solo numeri e id opachi
    assert set(futuri) == set(storie)
    assert futuri["Monitor 27 pollici"] == [(8.0, 10.0, 12.0), (7.0, 11.0, 13.0)]
    assert futuri["Rossi Srl"][0] == (18.0, 20.0, 22.0) and futuri[42][0] == (28.0, 30.0, 32.0)


def test_prevedi_molte_a_blocchi_oltre_512(servizi):
    storie = {f"prodotto {i}": [(None, float(i))] * 6 for i in range(600)}
    futuri, _ = motore.prevedi_molte(storie, 1)
    assert len(servizi) == 2 and [len(c[1]["series"]) for c in servizi] == [512, 88]
    ids = [s["id"] for c in servizi for s in c[1]["series"]]
    assert len(set(ids)) == 600                                                        # id diversi anche tra i blocchi
    assert len(futuri) == 600 and futuri["prodotto 599"] == [(597.0, 599.0, 601.0)]


def test_prevedi_molte_senza_storie_non_chiama(servizi):
    assert motore.prevedi_molte({}, 3) == ({}, "")
    assert not servizi


def test_l_url_dell_assistente_si_copia_una_volta(db):
    migrazione = importlib.import_module("previsioni.migrations.0002_url_da_ai")
    migrazione.copia_url(apps, None)                                       # niente da copiare: nessun effetto
    assert not Parametro.objects.filter(chiave="previsioni.url_servizio").exists()
    Parametro.objects.create(chiave="ai.url_forecast", valore="http://adabox-forecast-1:8080")
    Parametro.objects.create(chiave="ai.url_forecast", valore="http://solo-per-l-azienda", azienda=Azienda.objects.get(pk=1))
    migrazione.copia_url(apps, None)
    assert list(Parametro.objects.filter(chiave="previsioni.url_servizio").values_list("valore", "azienda")) == \
        [("http://adabox-forecast-1:8080", None)]
    assert servizio.url() == "http://adabox-forecast-1:8080"
    # una volta sola: quella nuova, se c'è, non si tocca più
    Parametro.objects.filter(chiave="ai.url_forecast", azienda__isnull=True).update(valore="http://altro:8080")
    migrazione.copia_url(apps, None)
    assert servizio.url() == "http://adabox-forecast-1:8080"


def test_l_url_vuoto_dell_assistente_non_si_copia(db):
    migrazione = importlib.import_module("previsioni.migrations.0002_url_da_ai")
    Parametro.objects.create(chiave="ai.url_forecast", valore="  ")
    migrazione.copia_url(apps, None)
    assert not Parametro.objects.filter(chiave="previsioni.url_servizio").exists()
    # quella nuova vuota si riempie con quella dell'assistente
    Parametro.objects.filter(chiave="ai.url_forecast").update(valore="http://forecast:8080")
    Parametro.objects.create(chiave="previsioni.url_servizio", valore="")
    migrazione.copia_url(apps, None)
    assert servizio.url() == "http://forecast:8080"
