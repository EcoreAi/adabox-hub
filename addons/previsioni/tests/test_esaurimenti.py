"""«Articoli in esaurimento» (vista di sola lettura sulle previsioni salvate) e il riquadro nella scheda prodotto."""
import datetime
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from core.models import Azienda
from core.viste import interroga
from core.viste.interroga import richiesta_di
from previsioni.models import PrevisioneArticolo, StatoCalcolo

pytestmark = pytest.mark.django_db

OGGI = timezone.localdate()


def _giorni(n):
    return OGGI + datetime.timedelta(days=n)


def _riga(azienda, nome, riordino, magazzino="", prodotto_pk=None, **extra):
    campi = dict(azienda=azienda, prodotto_pk=prodotto_pk or abs(hash(nome)) % 10**6, prodotto=nome, magazzino=magazzino,
                 magazzino_pk=1 if magazzino else None, per="mese", partenza=Decimal("100"), futuro=[["x", 1, 2, 3]] * 12,
                 consumo_mensile=Decimal("10"), riordino=riordino, stato="ok", calcolata_il=timezone.now(),
                 affidabilita={"livello": "media", "motivi": ["Storia: 14 mesi"]}, modello="timestral-1")
    campi.update(extra)
    return PrevisioneArticolo.objects.create(**campi)


@pytest.fixture
def capo(client):
    utente = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(utente)
    return utente


def test_lista_ordinata_per_riordino_e_filtro_entro_30_giorni(client, capo):
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Gamma", None)
    _riga(azienda, "Beta", _giorni(60))
    _riga(azienda, "Alfa", _giorni(10))
    _riga(azienda, "Delta", _giorni(20), magazzino="Negozio")
    url = reverse("previsioni:esaurimenti_lista")
    html = client.get(url).content.decode()
    posizioni = [html.index(n) for n in ("Alfa", "Delta", "Beta", "Gamma")]
    assert posizioni == sorted(posizioni)                                  # riordino crescente, senza data in fondo
    assert "Tutti i magazzini" in html and "Negozio" in html
    html = client.get(url, {"entro": "30"}).content.decode()
    assert "Alfa" in html and "Delta" in html and "Beta" not in html and "Gamma" not in html
    html = client.get(url, {"entro": "7"}).content.decode()
    assert "Alfa" not in html and "Delta" not in html
    html = client.get(url, {"f_magazzino": "Negozio"}).content.decode()
    assert "Delta" in html and "Alfa" not in html


def test_un_azienda_non_vede_le_righe_di_un_altra(client, capo):
    altra = Azienda.objects.create(nome="Altra Srl")
    _riga(altra, "Gamma", _giorni(5), magazzino="Segreto")
    _riga(Azienda.objects.get(pk=1), "Alfa", _giorni(5))
    html = client.get(reverse("previsioni:esaurimenti_lista")).content.decode()
    assert "Alfa" in html and "Gamma" not in html and "Segreto" not in html


def test_vista_in_sola_lettura(client, capo):
    riga = _riga(Azienda.objects.get(pk=1), "Alfa", _giorni(5))
    html = client.get(reverse("previsioni:esaurimenti_lista")).content.decode()
    assert "/esaurimenti/nuovo/" not in html
    assert client.get(reverse("previsioni:esaurimenti_nuovo")).status_code == 403
    assert client.get(reverse("previsioni:esaurimenti_modifica", args=[riga.pk])).status_code == 403
    assert client.post(reverse("previsioni:esaurimenti_elimina", args=[riga.pk])).status_code == 403
    assert client.get(reverse("previsioni:esaurimenti_dettaglio", args=[riga.pk])).status_code == 200
    assert PrevisioneArticolo.objects.filter(pk=riga.pk).exists()


def test_ada_vede_la_vista(capo):
    richiesta = richiesta_di(capo, Azienda.objects.get(pk=1))
    assert "previsioni.esaurimenti" in {interroga.id_vista(v) for v in interroga.viste_accessibili(richiesta)}


pytest_prodotti = pytest.mark.skipif(not apps.is_installed("prodotti"), reason="serve Prodotti")


@pytest.fixture
def prodotto(db):
    from pathlib import Path

    import fiscale
    import prodotti
    from django.core.management import call_command

    from prodotti.models import Prodotto
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    return Prodotto.objects.create(azienda=Azienda.objects.get(pk=1), nome="Monitor")


def _scheda(client, prodotto):
    return client.get(reverse("prodotti:prodotti_dettaglio", args=[prodotto.pk])).content.decode()


@pytest_prodotti
def test_riquadro_nella_scheda_prodotto_con_fascia_affidabilita_e_attribuzione(client, capo, prodotto):
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Monitor", datetime.date(2027, 1, 25), prodotto_pk=prodotto.pk, magazzino="Negozio",
          esaurimento=datetime.date(2027, 3, 25), esaurimento_da=datetime.date(2027, 3, 8),
          esaurimento_a=datetime.date(2027, 4, 18), quantita_suggerita=Decimal("90"))
    _riga(azienda, "Monitor", None, prodotto_pk=prodotto.pk, stato="nessun_consumo")
    _riga(azienda, "Altro", _giorni(3), prodotto_pk=prodotto.pk + 1)
    html = _scheda(client, prodotto)
    assert "Finisce verso il 25/03/2027" in html and "tra il 08/03/2027 e il 18/04/2027" in html
    assert "Riordina entro il 25/01/2027" in html and "quantità suggerita 90" in html
    assert "Nessun consumo previsto" in html and "Affidabilità: media" in html and "Storia: 14 mesi" in html
    assert "modello timestral-1 · licenza Modified MIT di Mistral AI" in html and "calcolata il" in html
    assert html.index("Negozio") < html.index("Tutti i magazzini")           # la riga sul totale per ultima
    assert "non aggiornata dal" not in html


@pytest_prodotti
def test_riquadro_fuori_orizzonte_e_senza_righe(client, capo, prodotto):
    assert "Affidabilità" not in _scheda(client, prodotto)                  # niente righe, niente riquadro
    _riga(Azienda.objects.get(pk=1), "Monitor", None, prodotto_pk=prodotto.pk, stato="ok",
          esaurimento=datetime.date(2027, 3, 25), esaurimento_da=datetime.date(2027, 3, 8), esaurimento_a=None)
    html = _scheda(client, prodotto)
    assert "Finisce verso il 25/03/2027" in html and "tra il 08/03/2027 e oltre il" in html
    assert "Riordina entro" not in html


@pytest_prodotti
def test_riquadro_avviso_se_non_aggiornata(client, capo, prodotto):
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Monitor", _giorni(9), prodotto_pk=prodotto.pk)
    ok = timezone.make_aware(datetime.datetime(2026, 11, 20, 2, 0))
    StatoCalcolo.objects.create(azienda=azienda, cosa="magazzino", ultimo_ok=ok, errore="servizio giù")
    assert "non aggiornata dal 20/11/2026" in _scheda(client, prodotto)
