"""Pagina Applicazioni: in cima la ricerca per parole e i filtri per stato e categoria, su tutte le sezioni (prima c'era
solo una ricerca in «Da acquistare», in fondo, e le app attive, la lista lunga, non si potevano cercare). Il filtro lo
fa core/applicazioni.js nel browser: qui si controlla ciò che gli serve nella pagina; lo script è provato con jsdom."""
import re
from collections import Counter

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from core import applicazioni

pytestmark = pytest.mark.django_db


@pytest.fixture
def pagina(client, superuser):
    client.force_login(superuser)
    return client.get(reverse("core:applicazioni")).content.decode()


def test_la_barra_sta_in_cima_prima_di_tutte_le_sezioni(pagina):
    assert 'id="mk-barra"' in pagina and 'id="mk-cerca"' in pagina and 'id="mk-vuoto" hidden' in pagina
    sezioni = [m.start() for m in re.finditer(r'<section class="mk-sezione" data-gruppo="', pagina)]
    assert sezioni and pagina.index('id="mk-barra"') < min(sezioni)
    assert set(re.findall(r'<section class="mk-sezione" data-gruppo="(\w+)"', pagina)) <= {"suite", "attive", "ferme", "altre"}
    assert "mk-filtri" not in pagina                               # la ricerca di prima, solo in «Da acquistare»
    assert "core/applicazioni.js" in pagina


def test_stati_e_categorie_con_quante_app(pagina):
    voci = applicazioni.voci()
    assert f'data-stato="" aria-pressed="true">Tutte <span class="mk-chip-n">{len(voci)}</span>' in pagina
    attive = sum(v["stato"] == applicazioni.ATTIVA for v in voci)
    assert f'data-stato="attive" aria-pressed="false">Attive <span class="mk-chip-n">{attive}</span>' in pagina
    for categoria, n in Counter(v["categoria"] for v in voci).items():
        assert f'<option value="{categoria}">{categoria} ({n})</option>' in pagina


def test_ogni_scheda_ha_il_testo_in_cui_si_cerca(pagina):
    """Nome, categoria, riassunto e funzioni; non i bottoni («Attiva», «Disattiva»), che farebbero trovare tutto."""
    schede = re.findall(r'<article class="mk-app is-\w+"[^>]*data-categoria="([^"]*)" data-cerca="([^"]*)"', pagina)
    assert len(schede) == len(applicazioni.voci())
    v = next(v for v in applicazioni.voci() if v["stato"] == applicazioni.ATTIVA and v["funzioni"])
    cerca = next(c for _, c in schede if c.startswith(v["nome"]))
    assert v["categoria"] in cerca and v["funzioni"][0] in cerca and "Disattiva" not in cerca


def test_lo_script_filtra_per_parole_stato_e_categoria():
    js = open(finders.find("core/applicazioni.js"), encoding="utf-8").read()
    for pezzo in ("dataset.cerca", "normalize('NFD')", "parole.every", "sezione.dataset.gruppo === stato",
                  "app.dataset.categoria === cat", "sezione.hidden", "replaceState"):
        assert pezzo in js, pezzo
