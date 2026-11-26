"""«Articoli in esaurimento» (vista di sola lettura sulle previsioni salvate) e il riquadro nella scheda prodotto."""
import datetime
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission, User
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core import parametri
from core.models import Azienda, Modulo, RegolaRiga, Ruolo
from core.viste import interroga
from core.viste.interroga import richiesta_di
from previsioni.models import PrevisioneArticolo, StatoCalcolo

pytestmark = pytest.mark.django_db
# «Articoli in esaurimento» si apre solo con Magazzino (e le sue righe nascono solo con Magazzino installato)
serve_magazzino = pytest.mark.skipif(not all(apps.is_installed(a) for a in ("magazzino", "prodotti")),
                                     reason="serve Magazzino con Prodotti")

OGGI = timezone.localdate()


def _giorni(n):
    return OGGI + datetime.timedelta(days=n)


def _riga(azienda, nome, riordino, magazzino="", prodotto_pk=None, **extra):
    campi = dict(azienda=azienda, prodotto_pk=prodotto_pk or abs(hash(nome)) % 10**6, prodotto=nome, magazzino=magazzino,
                 magazzino_pk=len(magazzino) if magazzino else None, per="mese", partenza=Decimal("100"), futuro=[["x", 1, 2, 3]] * 12,
                 consumo_mensile=Decimal("10"), riordino=riordino, stato="ok", calcolata_il=timezone.now(),
                 affidabilita={"livello": "media", "motivi": ["Storia: 14 mesi"]}, modello="timestral-1")
    campi.update(extra)
    return PrevisioneArticolo.objects.create(**campi)


@pytest.fixture
def capo(client):
    utente = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(utente)
    return utente


@serve_magazzino
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


@serve_magazzino
def test_un_azienda_non_vede_le_righe_di_un_altra(client, capo):
    altra = Azienda.objects.create(nome="Altra Srl")
    _riga(altra, "Gamma", _giorni(5), magazzino="Segreto")
    _riga(Azienda.objects.get(pk=1), "Alfa", _giorni(5))
    html = client.get(reverse("previsioni:esaurimenti_lista")).content.decode()
    assert "Alfa" in html and "Gamma" not in html and "Segreto" not in html


@serve_magazzino
def test_vista_in_sola_lettura(client, capo):
    riga = _riga(Azienda.objects.get(pk=1), "Alfa", _giorni(5))
    html = client.get(reverse("previsioni:esaurimenti_lista")).content.decode()
    assert "/esaurimenti/nuovo/" not in html
    assert client.get(reverse("previsioni:esaurimenti_nuovo")).status_code == 403
    assert client.get(reverse("previsioni:esaurimenti_modifica", args=[riga.pk])).status_code == 403
    assert client.post(reverse("previsioni:esaurimenti_elimina", args=[riga.pk])).status_code == 403
    assert client.get(reverse("previsioni:esaurimenti_dettaglio", args=[riga.pk])).status_code == 200
    assert PrevisioneArticolo.objects.filter(pk=riga.pk).exists()


@serve_magazzino
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
    assert "non aggiornate dal" not in html and "non calcolate" not in html


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
    assert "Previsioni non aggiornate dal 20/11/2026" in _scheda(client, prodotto)


@pytest_prodotti
def test_riquadro_stati_riordina_ora_finito_oltre(client, capo, prodotto):
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Monitor", OGGI, prodotto_pk=prodotto.pk, magazzino="Negozio", stato="riordina_ora",
          quantita_suggerita=Decimal("40"))
    _riga(azienda, "Monitor", None, prodotto_pk=prodotto.pk, magazzino="Deposito", stato="finito")
    _riga(azienda, "Monitor", None, prodotto_pk=prodotto.pk, stato="oltre")
    html = _scheda(client, prodotto)
    assert "Riordina ora" in html and "quantità suggerita 40" in html and "Finito" in html
    assert "Basta oltre il " in html
    assert "Finisce verso" not in html and "Riordina entro" not in html


@serve_magazzino
def test_lista_con_data_del_calcolo_e_avviso_se_non_aggiornata(client, capo):
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Alfa", _giorni(5), calcolata_il=timezone.make_aware(datetime.datetime(2026, 11, 22, 2, 0)))
    url = reverse("previsioni:esaurimenti_lista")
    html = client.get(url).content.decode()
    assert "calcolate il 22/11/2026" in html and "non aggiornate dal" not in html
    StatoCalcolo.objects.create(azienda=azienda, cosa="magazzino", errore="servizio giù",
                                ultimo_ok=timezone.make_aware(datetime.datetime(2026, 11, 20, 2, 0)))
    assert "non aggiornate dal 20/11/2026" in client.get(url).content.decode()


@serve_magazzino
def test_entro_resta_nel_form_dei_filtri(client, capo):
    _riga(Azienda.objects.get(pk=1), "Alfa", _giorni(5))
    url = reverse("previsioni:esaurimenti_lista")
    assert 'name="entro" value="30"' in client.get(url, {"entro": "30"}).content.decode()
    assert 'name="entro"' not in client.get(url).content.decode()


@serve_magazzino
def test_esaurimento_con_la_fascia_10_90(client, capo):
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Alfa", _giorni(5), esaurimento=datetime.date(2027, 3, 12), esaurimento_da=datetime.date(2027, 3, 8),
          esaurimento_a=datetime.date(2027, 4, 18))
    _riga(azienda, "Beta", _giorni(6), esaurimento=datetime.date(2027, 3, 12), esaurimento_da=datetime.date(2027, 3, 8),
          esaurimento_a=None)
    html = client.get(reverse("previsioni:esaurimenti_lista")).content.decode()
    assert "12/03/2027 (08/03/2027 – 18/04/2027)" in html
    assert "12/03/2027 (08/03/2027 – oltre " in html


# ---------- le previsioni del magazzino solo a chi vede Magazzino (spec, «4 quater. Permessi») ----------

def _utente(client, azienda, *permessi, ruolo=None):
    u = User.objects.create_user("vera", "vera@example.com", "x")
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita, u.profilo.ruolo = azienda, ruolo
    u.profilo.save()
    for p in permessi:
        app, codename = p.split(".")
        u.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
    client.force_login(u)
    return User.objects.get(pk=u.pk)


def _viste(utente, azienda):
    return {interroga.id_vista(v) for v in interroga.viste_accessibili(richiesta_di(utente, azienda))}


@serve_magazzino
def test_senza_permessi_di_magazzino_niente_previsioni_del_magazzino(client, prodotto):
    """Solo i permessi delle previsioni: né la lista, né la sezione della pagina, né il riquadro, né Ada. Con il
    permesso delle giacenze di Magazzino (magazzino.view_movimento) sì."""
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Monitor", _giorni(10), prodotto_pk=prodotto.pk, magazzino="Cagliari")
    u = _utente(client, azienda, "previsioni.view_previsionearticolo", "previsioni.view_previsionepronta",
                "prodotti.view_prodotto")
    assert client.get(reverse("previsioni:esaurimenti_lista")).status_code == 403
    assert "Cagliari" not in client.get(reverse("previsioni:pagina")).content.decode()
    assert "Cagliari" not in _scheda(client, prodotto)
    assert "previsioni.esaurimenti" not in _viste(u, azienda)
    u.user_permissions.add(Permission.objects.get(content_type__app_label="magazzino", codename="view_movimento"))
    u = User.objects.get(pk=u.pk)
    client.force_login(u)
    assert "Cagliari" in client.get(reverse("previsioni:esaurimenti_lista")).content.decode()
    assert "Cagliari" in client.get(reverse("previsioni:pagina")).content.decode()
    assert "Cagliari" in _scheda(client, prodotto)
    assert "previsioni.esaurimenti" in _viste(u, azienda)


@pytest.mark.skipif(apps.is_installed("magazzino"), reason="solo senza Magazzino installato (collaudo del modulo da solo)")
def test_senza_magazzino_installato_niente_lista_ne_ada(client, capo):
    _riga(Azienda.objects.get(pk=1), "Alfa", _giorni(5))
    assert client.get(reverse("previsioni:esaurimenti_lista")).status_code == 403
    assert "previsioni.esaurimenti" not in _viste(capo, Azienda.objects.get(pk=1))


@serve_magazzino
def test_magazzino_non_attivo_per_l_azienda_niente_lista_ne_ada(client, capo):
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Alfa", _giorni(5))
    Modulo.objects.update_or_create(slug="magazzino", defaults={"nome": "Magazzino"})[0].aziende.set(
        [Azienda.objects.create(nome="Altra")])
    assert client.get(reverse("previsioni:esaurimenti_lista")).status_code == 403
    assert "previsioni.esaurimenti" not in _viste(capo, azienda)


@serve_magazzino
def test_la_regola_di_riga_della_vista_vale_anche_nel_riquadro_e_nella_pagina(client, prodotto):
    azienda = Azienda.objects.get(pk=1)
    ruolo = Ruolo.objects.create(nome="Solo Cagliari", livello_base="lavoro")
    RegolaRiga.objects.create(vista="previsioni.esaurimenti", ruolo=ruolo, campo="magazzino", operatore="uguale",
                              valore="Cagliari")
    _riga(azienda, "Monitor", _giorni(10), prodotto_pk=prodotto.pk, magazzino="Cagliari")
    _riga(azienda, "Monitor", _giorni(12), prodotto_pk=prodotto.pk, magazzino="Sassari")
    _utente(client, azienda, "previsioni.view_previsionearticolo", "magazzino.view_movimento", "prodotti.view_prodotto",
            ruolo=ruolo)
    scheda = _scheda(client, prodotto)
    assert "Cagliari" in scheda and "Sassari" not in scheda
    pagina = client.get(reverse("previsioni:pagina")).content.decode()
    assert "Cagliari" in pagina and "Sassari" not in pagina


@serve_magazzino
def test_righe_di_un_altra_azienda_mai_nella_sezione_ne_nel_riquadro(client, capo, prodotto):
    _riga(Azienda.objects.create(nome="Altra Srl"), "Monitor", _giorni(3), prodotto_pk=prodotto.pk, magazzino="Segreto")
    _riga(Azienda.objects.get(pk=1), "Alfa", _giorni(5))
    assert "Segreto" not in client.get(reverse("previsioni:pagina")).content.decode()
    assert "Segreto" not in _scheda(client, prodotto)


# ---------- un calcolo non riuscito si vede sempre, con il motivo e la data del tentativo ----------

TENTATIVO = timezone.make_aware(datetime.datetime(2026, 11, 24, 2, 0))
RIFIUTATO = "Il servizio di previsione ha rifiutato la richiesta: 401 chiave sbagliata"


def _fallito(azienda, ultimo_ok=None, cosa="magazzino", errore=RIFIUTATO):
    return StatoCalcolo.objects.create(azienda=azienda, cosa=cosa, ultimo_tentativo=TENTATIVO, ultimo_ok=ultimo_ok,
                                       errore=errore)


def _avvisa(html, titolo):
    return titolo in html and RIFIUTATO in html and "24/11/2026 02:00" in html


@serve_magazzino
def test_lista_dice_se_le_previsioni_non_sono_mai_state_calcolate(client, capo):
    azienda = Azienda.objects.get(pk=1)
    _fallito(azienda)
    url = reverse("previsioni:esaurimenti_lista")
    assert _avvisa(client.get(url).content.decode(), "Previsioni non calcolate")
    _riga(azienda, "Alfa", _giorni(5), calcolata_il=timezone.make_aware(datetime.datetime(2026, 11, 19, 2, 0)))
    StatoCalcolo.objects.update(ultimo_ok=timezone.make_aware(datetime.datetime(2026, 11, 20, 2, 0)))
    assert _avvisa(client.get(url).content.decode(), "Previsioni non aggiornate dal 20/11/2026")


@pytest_prodotti
def test_riquadro_dice_il_motivo_con_e_senza_righe(client, capo, prodotto):
    azienda = Azienda.objects.get(pk=1)
    _fallito(azienda)
    assert _avvisa(_scheda(client, prodotto), "Previsioni non calcolate")          # nessuna riga: il riquadro c'è lo stesso
    _riga(azienda, "Monitor", _giorni(9), prodotto_pk=prodotto.pk,
          calcolata_il=timezone.make_aware(datetime.datetime(2026, 11, 18, 2, 0)))
    assert _avvisa(_scheda(client, prodotto), "Previsioni non aggiornate dal 18/11/2026")


# ---------- attribuzione, riquadro come nella spec (§4, §8) ----------

def test_attribuzione_senza_nome_del_modello():
    assert render_to_string("previsioni/_attribuzione.html", {"modello": "timestral-1"}).strip() == (
        '<span class="sub">modello timestral-1 · licenza Modified MIT di Mistral AI</span>')
    assert render_to_string("previsioni/_attribuzione.html", {"modello": ""}).strip() == (
        '<span class="sub">licenza Modified MIT di Mistral AI</span>')


@serve_magazzino
def test_lista_con_l_attribuzione_sotto_la_tabella(client, capo):
    _riga(Azienda.objects.get(pk=1), "Alfa", _giorni(5))
    html = client.get(reverse("previsioni:esaurimenti_lista")).content.decode()
    assert html.count("modello timestral-1 · licenza Modified MIT di Mistral AI") == 1
    assert html.index("Alfa") < html.index("licenza Modified MIT")


@pytest_prodotti
def test_riquadro_con_giacenza_e_consumo_e_aggiorna(client, capo, prodotto):
    """Spec §4: «Giacenza prevista X · consumo previsto Y al mese (fascia a–b)»; §8: «Aggiorna» anche nel riquadro (POST,
    con il permesso della pagina), solo con il servizio configurato."""
    azienda = Azienda.objects.get(pk=1)
    _riga(azienda, "Monitor", _giorni(9), prodotto_pk=prodotto.pk, partenza=Decimal("120"), consumo_mensile=Decimal("45"),
          futuro=[["x", 30, 45, 60]] * 12)
    _riga(azienda, "Monitor", _giorni(9), prodotto_pk=prodotto.pk, magazzino="Negozio", per="settimana",
          partenza=Decimal("8.5"), consumo_mensile=Decimal("13"), futuro=[["x", 2.4, 3, 6]] * 52)
    html = _scheda(client, prodotto)
    unita = f" {prodotto.unita}"
    assert f"Giacenza prevista 120{unita} · consumo previsto 45{unita} al mese (fascia 30–60)" in html
    assert f"Giacenza prevista 8,5{unita} · consumo previsto 13{unita} al mese (fascia 10,4–26)" in html   # × 52 / 12
    aggiorna = f'action="{reverse("previsioni:aggiorna")}?cosa=magazzino"'
    assert aggiorna not in html                                         # servizio non configurato
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    html = _scheda(client, prodotto)
    assert aggiorna in html and 'method="post"' in html and "csrfmiddlewaretoken" in html
    _utente(client, azienda, "previsioni.view_previsionearticolo", "magazzino.view_movimento", "prodotti.view_prodotto")
    html = _scheda(client, prodotto)
    assert "Giacenza prevista 120" in html and aggiorna not in html    # senza il permesso di modifica
