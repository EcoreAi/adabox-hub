import datetime
import xml.etree.ElementTree as ET

import pytest
from django.utils import timezone

from core import svg
from core.models import Lavoro
from core.tests.urls_viste import VISTA
from core.viste import grafico

pytestmark = [pytest.mark.urls("core.tests.urls_viste"), pytest.mark.django_db]


@pytest.fixture
def lavori(db):
    for f, stato, t, mese in [("a", "fatto", 2, 9), ("b", "fatto", 3, 10), ("c", "in_coda", 1, 10), ("d", "fallito", 0, 10)]:
        Lavoro.objects.create(funzione=f, stato=stato, tentativi=t,
                              esegui_dopo=timezone.make_aware(datetime.datetime(2026, mese, 5, 12)))


def test_dati_count_e_sum(lavori):
    qs = Lavoro.objects.all()
    assert dict(grafico.dati(VISTA, qs, "count", "stato")) == {"In coda": 1, "Fatto": 2, "Fallito": 1}
    assert dict(grafico.dati(VISTA, qs, "sum:tentativi", "stato"))["Fatto"] == 5
    assert grafico.dati(VISTA, qs, "count", "esegui_dopo:mese") == [("settembre 2026", 1), ("ottobre 2026", 3)]


def test_limite_categorie(db, monkeypatch):
    monkeypatch.setattr(grafico, "MAX_CATEGORIE", 3)
    for i in range(5):
        for _ in range(i + 1):
            Lavoro.objects.create(funzione=f"f{i}")
    monkeypatch.setattr(VISTA, "graph", {**VISTA.graph, "per": ["funzione"]})
    dati = grafico.dati(VISTA, Lavoro.objects.all(), "count", "funzione")
    assert dati == [("f4", 5), ("f3", 4), ("Altro", 6)]


@pytest.mark.parametrize("tipo", ["barre", "linee", "torta"])
def test_svg_valido(tipo):
    markup = svg.DISEGNI[tipo]([("Uno & due", 3), ("Tre", 0), ("Quattro", 7.5)], "Prova <titolo>")
    radice = ET.fromstring(markup)
    assert radice.tag.endswith("svg") and radice.get("role") == "img"
    assert ET.fromstring(svg.DISEGNI[tipo]([], "Vuoto")) is not None
    assert ET.fromstring(svg.DISEGNI[tipo]([("Solo", 4)], "Uno")) is not None


def test_pagina(client, superuser, lavori):
    r = client.get("/prova/lavori/grafico/", {"tipo": "torta", "misura": "sum:tentativi", "per": "stato", "f_stato": "fatto"})
    assert r.status_code == 200 and r.context["tipo"] == "torta"
    assert r.context["righe"] == [("Fatto", "5")] and r.context["titolo"] == "Somma di tentativi per stato"
    assert "<svg" in r.content.decode()


def test_parametri_non_ammessi(client, superuser, lavori):
    r = client.get("/prova/lavori/grafico/", {"tipo": "radar", "misura": "sum:funzione", "per": "pk"})
    assert (r.context["tipo"], r.context["misura"], r.context["per"]) == ("barre", "count", "stato")


NOME_LUNGO = "Ferramenta e Utensili Rossi & Bianchi Srl"
NOME_APOSTROFO = "Ferramenta Dell'Orto e Figli Utensileria SpA"


@pytest.mark.parametrize("tipo", ["barre", "torta"])
@pytest.mark.parametrize("nome", [NOME_LUNGO, NOME_APOSTROFO, "Rossi & Bianchi & Verdi & Neri & Gialli & Blu"])
@pytest.mark.parametrize("quanti", [3, 10])
def test_etichette_accorciate_senza_pezzi_di_entita(tipo, nome, quanti):
    """Il taglio non deve cadere dentro «&amp;» / «&#x27;»: il nome accorciato ha solo caratteri veri."""
    dati = [(nome, 5)] + [(f"Cliente {i}", i) for i in range(1, quanti)]
    radice = ET.fromstring(svg.DISEGNI[tipo](dati, "Fatturato per cliente"))     # XML valido
    testi = ["".join(t.itertext()) for t in radice.iter("{http://www.w3.org/2000/svg}text")]
    accorciati = [t for t in testi if t.startswith(nome[:20])]
    assert accorciati
    for t in accorciati:
        assert not t.startswith(nome) or len(nome) <= 30
        assert "&a" not in t and "&#" not in t and "&q" not in t
        assert t.split(" ")[0] and (nome in t or "…" in t)
        parola = t.split("…")[0]
        assert nome.startswith(parola)             # un prefisso vero del nome, senza residui
