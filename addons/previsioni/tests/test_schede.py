"""Le schede della pagina «Previsioni»: Vendite, Magazzino, Le mie previsioni; solo la scelta si costruisce."""
import pytest
from django.apps import apps
from django.urls import reverse

from core.models import Azienda
from previsioni import pronte
from previsioni.tests.test_esaurimenti import _giorni, _riga, prodotto  # noqa: F401
from previsioni.tests.test_pagina import _pagina, _riserva, _salva_tutte, azienda, capo, servizi  # noqa: F401

pytestmark = [pytest.mark.django_db,
              pytest.mark.skipif(not all(apps.is_installed(a) for a in ("vendite", "magazzino", "prodotti", "ai")),
                                 reason="serve Vendite, Magazzino, Prodotti e Assistente AI")]

CARD = reverse("previsioni:pronta", args=["vendite.prodotti"])
BARRA = 'id="prev-barra"'


def _con_dati(azienda):
    _salva_tutte(azienda)
    _riga(azienda, "Monitor", _giorni(10), magazzino="Negozio")


def _mie(capo, azienda):
    from previsioni.tests.test_le_mie import _artifact
    _artifact(capo, azienda, "Fatturato 2027")


def _attiva(html):
    import re
    return re.findall(r'<a class="prev-scheda is-attiva" href="([^"]*)" aria-current="page"', html)


def test_default_vendite_solo_la_sua_sezione(client, capo, azienda, servizi):
    _con_dati(azienda)
    _mie(capo, azienda)
    html = _pagina(client)
    assert CARD in html and "Negozio" not in html and BARRA not in html and 'ui-card-title">Articoli in esaurimento' not in html
    assert _attiva(html) == [f'{reverse("previsioni:pagina")}?scheda=vendite']
    assert html.count('prev-scheda is-attiva') == 1
    assert "?scheda=magazzino" in html and "?scheda=mie" in html


def test_scheda_magazzino(client, capo, azienda, servizi):
    _con_dati(azienda)
    html = _pagina(client, "magazzino")
    assert "Negozio" in html and CARD not in html and BARRA not in html and "Calcolo in corso" not in html
    assert _attiva(html) == [f'{reverse("previsioni:pagina")}?scheda=magazzino']


def test_scheda_mie_con_filtri_nell_indirizzo(client, capo, azienda, servizi):
    _con_dati(azienda)
    _mie(capo, azienda)
    r = client.get(reverse("previsioni:pagina"), {"scheda": "mie", "q": "fatturato", "salvate": "1"})
    html = r.content.decode()
    assert r.status_code == 200 and BARRA in html and "Fatturato 2027" in html
    assert CARD not in html and "Negozio" not in html
    assert _attiva(html) == [f'{reverse("previsioni:pagina")}?scheda=mie']
    assert '<span class="prev-conta">1</span>' in html


def test_il_javascript_dei_filtri_conserva_la_scheda():
    """mie.js riscrive solo i propri parametri dell'indirizzo: `scheda` resta."""
    import pathlib
    js = (pathlib.Path(apps.get_app_config("previsioni").path) / "static/previsioni/mie.js").read_text()
    assert "new URL(window.location.href)" in js and "url.search =" not in js and "'scheda'" not in js


@pytest.mark.parametrize("scheda", ["inventata", "", "MIE", "../x", "magazzino\x00"])
def test_scheda_sconosciuta_torna_al_default(client, capo, azienda, servizi, scheda):
    _con_dati(azienda)
    r = client.get(reverse("previsioni:pagina"), {"scheda": scheda})
    html = r.content.decode()
    assert r.status_code == 200 and CARD in html and "Negozio" not in html
    assert _attiva(html) == [f'{reverse("previsioni:pagina")}?scheda=vendite']


def test_scheda_non_disponibile_torna_al_default(client, capo, azienda, servizi):
    _con_dati(azienda)
    _riserva("magazzino", Azienda.objects.create(nome="Altra"))
    r = client.get(reverse("previsioni:pagina"), {"scheda": "magazzino"})
    html = r.content.decode()
    assert r.status_code == 200 and CARD in html and "Negozio" not in html and "?scheda=magazzino" not in html
    assert _attiva(html) == [f'{reverse("previsioni:pagina")}?scheda=vendite']


def test_un_solo_scheda_niente_schede(client, capo, azienda, servizi, monkeypatch):
    _con_dati(azienda)
    vera = pronte.app_attiva
    monkeypatch.setattr(pronte, "app_attiva", lambda slug, *a, **k: slug not in ("ai", "grafici") and vera(slug, *a, **k))
    _riserva("magazzino", Azienda.objects.create(nome="Altra"))
    html = _pagina(client)
    assert "prev-schede" not in html and "prev-scheda" not in html and CARD in html


def test_senza_vendite_la_prima_e_magazzino(client, capo, azienda, servizi):
    _con_dati(azienda)
    _riserva("vendite", Azienda.objects.create(nome="Altra"))
    html = _pagina(client)
    assert "Negozio" in html and CARD not in html
    assert _attiva(html) == [f'{reverse("previsioni:pagina")}?scheda=magazzino']


def test_aggiorna_torna_alla_stessa_scheda(client, capo, azienda, servizi, monkeypatch):
    monkeypatch.setattr("previsioni.views.lavori.accoda", lambda *a, **k: None)
    pagina = reverse("previsioni:pagina")
    for cosa in ("vendite", "magazzino"):
        r = client.post(f'{reverse("previsioni:aggiorna")}?cosa={cosa}', HTTP_REFERER=f"http://testserver{pagina}?scheda={cosa}")
        assert r.status_code == 302 and r.url == f"http://testserver{pagina}?scheda={cosa}"
        assert client.post(f'{reverse("previsioni:aggiorna")}?cosa={cosa}').url == f"{pagina}?scheda={cosa}"
    r = client.post(f'{reverse("previsioni:aggiorna")}?cosa=vendite', HTTP_REFERER="http://evil.example/?scheda=mie")
    assert r.url == f"{pagina}?scheda=vendite"
