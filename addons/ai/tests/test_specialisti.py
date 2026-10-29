import datetime

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from ai import artifact, motore, specialisti, strumenti
from ai.gateway import finto
from ai.models import AnelloCatena, Artifact, Conversazione, Evento, Modello, Profilo, Provider
from ai.strumenti import specialisti as strumenti_specialisti
from core import parametri
from core.models import Azienda, Lavoro


@pytest.fixture
def servizi(monkeypatch):
    chiamate = []

    def chiama(chiave, percorso, dati, nome):
        chiamate.append((chiave, percorso, dati))
        if chiave == "url_forecast":
            ultimo = dati["series"][0]["values"][-1]
            return {"model": "finto-timestral", "forecasts": [{"id": "serie", "quantiles": {
                "0.1": [ultimo - 2 - i for i in range(dati["horizon"])],
                "0.5": [ultimo + i for i in range(dati["horizon"])],
                "0.9": [ultimo + 2 + i for i in range(dati["horizon"])]}}]}
        return {"answers": {"d": {"type": "noul", "noul": 0.91, "backend": "embed_sim"}}}
    monkeypatch.setattr(specialisti, "chiama", chiama)
    return chiamate


@pytest.fixture
def scena(db, client):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    oggi = timezone.localdate().replace(day=15)
    for mesi_fa, quanti in [(8, 2), (7, 3), (6, 3), (5, 4), (4, 4), (3, 5), (2, 5), (1, 6), (0, 9)]:
        mese = specialisti.avanti(oggi.replace(day=1), "mese", -mesi_fa)
        for _ in range(quanti):
            lavoro = Lavoro.objects.create(funzione="prova.lavoro")
            Lavoro.objects.filter(pk=lavoro.pk).update(creato=timezone.make_aware(
                datetime.datetime.combine(mese.replace(day=10), datetime.time(9))))
    return {"capo": capo, "azienda": Azienda.objects.get(pk=1), "client": client,
            "conversazione": Conversazione.objects.create(utente=capo)}


def _contesto(scena):
    return strumenti.Contesto(utente=scena["capo"], azienda=scena["azienda"], conversazione=scena["conversazione"])


def test_periodi():
    assert specialisti.avanti(datetime.date(2026, 11, 1), "mese", 2) == datetime.date(2027, 1, 1)
    assert specialisti.avanti(datetime.date(2026, 3, 1), "mese", -3) == datetime.date(2025, 12, 1)
    assert specialisti.inizio(datetime.date(2026, 10, 29), "settimana") == datetime.date(2026, 10, 26)
    assert specialisti.etichetta(datetime.date(2026, 10, 1), "mese") == "ott 2026"


def test_strumenti_solo_con_il_servizio_configurato(scena):
    nomi = {s.nome for s in strumenti.disponibili(scena["capo"])}
    assert "previsione" not in nomi and "classifica" not in nomi
    parametri.scrivi("ai.url_forecast", "http://forecast:8080")
    nomi = {s.nome for s in strumenti.disponibili(scena["capo"])}
    assert "previsione" in nomi and "classifica" not in nomi


def test_previsione_dalla_storia_vera(scena, servizi):
    r = strumenti_specialisti.previsione(_contesto(scena), "core.lavoro", "creato", per="mese", orizzonte=3)
    inviati = servizi[0][2]["series"][0]["values"]
    assert inviati == [2, 3, 3, 4, 4, 5, 5, 6]                     # il mese in corso (9) è escluso: incompleto
    assert servizi[0][2]["horizon"] == 3 and servizi[0][2]["quantiles"] == [0.1, 0.5, 0.9]
    assert r["previsione"][0] == {"periodo": specialisti.etichetta(specialisti.inizio(timezone.localdate(), "mese"),
                                                                    "mese"), "basso_10": 4.0, "mediana": 6.0,
                                  "alto_90": 8.0}
    a = Artifact.objects.get()
    assert a.spec["grafico"] == "previsione" and len(a.dati["storico"]) == 8 and len(a.dati["futuro"]) == 3
    disegno = artifact.svg_di(a)
    assert disegno.startswith("<svg") and "Fascia 10-90 %" in disegno and "stroke-dasharray" in disegno
    csv = artifact.csv_di(a, a.dati)
    assert "Previsione mediana" in csv and csv.count("\n") == 12


def test_previsione_rifiuta_storie_corte_e_campi_non_data(scena, servizi):
    with pytest.raises(strumenti.ErroreStrumento, match="almeno 6 periodi"):
        strumenti_specialisti.previsione(_contesto(scena), "core.lavoro", "creato",
                                         filtri={"creato__gte": str(timezone.localdate() - datetime.timedelta(days=100))})
    with pytest.raises(strumenti.ErroreStrumento, match="non è un campo data"):
        strumenti_specialisti.previsione(_contesto(scena), "core.lavoro", "funzione")
    assert not servizi


def test_previsione_mai_negativa_per_serie_positive(scena, monkeypatch):
    monkeypatch.setattr(specialisti, "chiama", lambda *a: {"forecasts": [{"quantiles": {
        "0.1": [-3.0], "0.5": [1.0], "0.9": [4.0]}}]})
    futuro, _ = specialisti.prevedi([(None, 1.0)] * 6, 1)
    assert futuro == [(0.0, 1.0, 4.0)]


def test_servizio_giu_messaggio_chiaro(scena, monkeypatch):
    parametri.scrivi("ai.url_forecast", "http://127.0.0.1:9")                   # porta chiusa
    monkeypatch.setattr(specialisti, "TIMEOUT", 2)
    with pytest.raises(strumenti.ErroreStrumento, match="non risponde"):
        strumenti_specialisti.previsione(_contesto(scena), "core.lavoro", "creato")


def test_dal_motore_con_grafico_e_numeri_verificati(scena, servizi):
    parametri.scrivi("ai.url_forecast", "http://forecast:8080")
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)
    with finto.con_copione([[("strumento", "previsione", {"vista": "core.lavoro", "data": "creato"})],
                            ["Il mese prossimo circa 7 lavori (tra 5 e 9)."]]):
        turno = motore.avvia(scena["conversazione"], "Quanti lavori nei prossimi mesi?", scena["capo"],
                             scena["azienda"])
    turno.refresh_from_db()
    assert not Evento.objects.get(tipo="strumento").dati["risultati"][0]["errore"]
    assert turno.provenienza["esito"] == "verificato"
    html = scena["client"].get(f"/ai/chat/{scena['conversazione'].pk}/").content.decode()
    assert "Fascia 10-90 %" in html
    pagina = scena["client"].get(f"/ai/artifact/{Artifact.objects.get().pk}/").content.decode()
    assert "Mediana" in pagina and "finto-timestral" in pagina


def test_classifica(scena, servizi):
    r = strumenti_specialisti.classifica(_contesto(scena), "Il server è fermo", "È urgente?")
    assert r["noul"] == 0.91 and "indicative" in r["nota"]
    assert servizi[0][2]["questions"]["d"] == {"type": "noul", "instructions": "È urgente?"}
    with pytest.raises(strumenti.ErroreStrumento, match="opzioni"):
        strumenti_specialisti.classifica(_contesto(scena), "x", "y", tipo="scelta")


def test_filtro_con_data_su_campo_data_e_ora(scena, recwarn):
    from ai.strumenti import viste
    oggi = timezone.localdate()
    r = viste.aggrega_record(_contesto(scena), "core.lavoro", filtri={"creato__gte": oggi.replace(day=1).isoformat()})
    assert r["totale"] == 9 and not [w for w in recwarn if "naive datetime" in str(w.message)]


@pytest.mark.parametrize("modulo", ["ai.specialisti", "ai.pianificate", "ai.conoscenza", "ai.protezione",
                                    "ai.artifact", "ai.strumenti"])
def test_ogni_modulo_si_importa_per_primo(modulo):
    """Il worker e i comandi caricano i moduli in ordini diversi: nessun import circolare a seconda di chi parte."""
    import subprocess
    import sys

    from django.conf import settings
    esito = subprocess.run([sys.executable, "-c", f"import django; django.setup(); import {modulo}"],
                           cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=120)
    assert esito.returncode == 0, esito.stderr[-1500:]


def test_totale_sull_orizzonte_ed_etichette_dell_asse(scena, servizi):
    r = strumenti_specialisti.previsione(_contesto(scena), "core.lavoro", "creato", per="settimana", orizzonte=13)
    t = r["totale_orizzonte"]
    assert t["periodi"] == 13 and t["mediana"] == round(sum(p["mediana"] for p in r["previsione"]), 2)
    assert t["basso_10"] <= t["mediana"] <= t["alto_90"]
    disegno = artifact.svg_di(Artifact.objects.get())
    assert disegno.count('transform="rotate(-35') <= 11                     # una decina di etichette, non 40
    pagina = scena["client"].get(f"/ai/artifact/{Artifact.objects.get().pk}/").content.decode()
    assert "Totale (13 periodi)" in pagina
