"""La previsione per gruppo nel costruttore di Analisi: «Raggruppa per» e «Primi», salvata e mostrata come tabella."""
import datetime
import re

import pytest
from django.apps import apps
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from core import parametri
from core.models import Azienda, Lavoro
from core.viste import interroga
from core.viste.interroga import richiesta_di
from previsioni import motore, servizio

pytestmark = [pytest.mark.django_db, pytest.mark.skipif(not apps.is_installed("grafici"), reason="serve Analisi")]

if apps.is_installed("grafici"):
    from grafici import costruttore
    from grafici import motore as motore_grafici
    from grafici.models import Grafico, Pagina


@pytest.fixture
def capo(client):
    u = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(u)
    return u


@pytest.fixture
def servizi(monkeypatch):
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")

    def chiama(percorso, dati):
        return {"model": "finto-timestral", "forecasts": [{"id": s["id"], "quantiles": {
            "0.1": [s["values"][-1] - 2 - i for i in range(dati["horizon"])],
            "0.5": [s["values"][-1] + i for i in range(dati["horizon"])],
            "0.9": [s["values"][-1] + 2 + i for i in range(dati["horizon"])]}} for s in dati["series"]]}
    monkeypatch.setattr(servizio, "chiama", chiama)


@pytest.fixture
def storia(db):
    for i, quanti in enumerate([5, 4, 3]):
        for m in range(1, 9):
            for _ in range(quanti):
                lavoro = Lavoro.objects.create(funzione=f"prova.f{i}")
                Lavoro.objects.filter(pk=lavoro.pk).update(creato=timezone.make_aware(datetime.datetime.combine(
                    motore.avanti(timezone.localdate().replace(day=1), "mese", -m).replace(day=10), datetime.time(9))))


DATI = {"vista": "core.lavoro", "tipo": "previsione", "misura": "count", "data": "creato", "periodo": "mese",
        "orizzonte": "3", "raggruppa": "funzione", "primi": "2"}


def test_costruttore_previsione_raggruppata_si_salva_e_si_vede_come_tabella(client, capo, servizi, storia):
    html = client.get(reverse("grafici:costruttore"), DATI).content.decode()
    assert "Totale previsto" in html and "prova.f0" in html and "prova.f2" not in html     # anteprima: i primi 2
    r = client.post(reverse("grafici:costruttore"), {**DATI, "titolo": "Lavori per funzione", "destinazione": "nuova",
                                                     "titolo_nuova": "Previsioni", "aggiorna_ogni": "0"})
    assert r.status_code == 302
    g = Grafico.objects.get(utente=capo)
    assert g.tipo == "previsione" and g.dati["tipo"] == "tabella" and g.dati["modello"] == "finto-timestral"
    assert g.spec == {"vista": "core.lavoro", "misura": "count", "data": "creato", "per": "mese", "orizzonte": 3,
                      "raggruppa": "funzione", "primi": 2}
    html = client.get(reverse("grafici:pagina", args=[Pagina.objects.get(titolo="Previsioni").pk])).content.decode()
    assert "<th>Gruppo</th>" in html and "prova.f1" in html and "modello finto-timestral" in html and "di 2 righe" not in html
    csv = client.get(reverse("grafici:grafico_csv", args=[g.pk])).content.decode("utf-8-sig")
    assert csv.startswith("Gruppo;") and "prova.f0" in csv and "Totale previsto" in csv
    html = client.get(reverse("grafici:grafico_costruttore", args=[g.pk])).content.decode()
    assert 'value="funzione" selected' in html and 'max="50" value="2"' in html


def test_senza_raggruppa_resta_la_previsione_di_una_serie(client, capo, servizi, storia):
    spec = costruttore.spec_di({k: v for k, v in DATI.items() if k not in ("raggruppa", "primi")})
    assert "raggruppa" not in spec and spec["per"] == "mese"
    html = client.get(reverse("grafici:costruttore"), {k: v for k, v in DATI.items() if k not in ("raggruppa", "primi")}).content.decode()
    assert "Totale previsto" not in html and 'value="mese" selected' in html


def test_raggruppa_tra_i_campi_della_vista(client, capo, servizi, storia):
    vista = motore_grafici.vista_di({"vista": "core.lavoro"}, richiesta_di(capo, Azienda.objects.get(pk=1)))
    attesi = [v for v, _ in interroga.opzioni_vista(vista)["raggruppamenti"] if ":" not in v]
    assert "funzione" in attesi
    html = client.get(reverse("grafici:costruttore"), {**DATI, "raggruppa": ""}).content.decode()
    m = re.search(r'<select class="ui-input" name="raggruppa"[^>]*>(.*?)</select>', html, re.S)
    scelte = re.findall(r'<option value="([^"]*)"', m.group(1))
    assert scelte == ["", *attesi]


def test_csv_della_previsione_raggruppata(capo):
    g = Grafico(tipo=Grafico.PREVISIONE)
    dati = {"tipo": "tabella", "colonne": ["Gruppo", "Totale"], "righe": [["a", "1"], ["b", "2"]]}
    assert motore_grafici.csv_di(g, dati).lstrip("﻿").splitlines() == ["Gruppo;Totale", "a;1", "b;2"]
