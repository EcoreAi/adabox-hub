"""La pagina «Previsioni» (una sezione per app), i widget della dashboard e la riga di Vendite nella scheda prodotto."""
import datetime

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from core import dashboard, parametri
from core.models import Azienda, Modulo
from core.viste.interroga import richiesta_di
from previsioni import pronte, servizio
from previsioni.models import PrevisioneArticolo, PrevisionePronta, StatoCalcolo
from previsioni.tests.test_esaurimenti import _giorni, _riga, prodotto  # noqa: F401  (la fixture `prodotto`)

pytestmark = [pytest.mark.django_db,
              pytest.mark.skipif(not all(apps.is_installed(a) for a in ("vendite", "magazzino", "prodotti")),
                                 reason="serve Vendite, Magazzino e Prodotti")]

ATTRIBUZIONE = "modello timestral-1 · licenza Modified MIT di Mistral AI"
FASCIA = {"livello": "media", "motivi": ["Storia: 14 mesi"]}


def _storico():
    return [[f"{m:02d}/2026", float(10 + m)] for m in range(1, 9)]


def _futuro():
    return [["09/2026", 8.0, 12.0, 16.0], ["10/2026", 9.0, 13.0, 17.0], ["11/2026", 10.0, 14.0, 18.0]]


def _totale():
    return {"basso_10": 27.0, "mediana": 39.0, "alto_90": 51.0}


def _gruppo(chiave, nome):
    return {"chiave": chiave, "nome": nome, "storico": _storico(), "futuro": _futuro(), "totale": _totale(),
            "affidabilita": FASCIA}


def _salva(azienda, chiave, risultato=None, errore="", calcolata_il=None):
    spec = pronte._registro[chiave].spec(azienda)
    dati = {"spec": spec, **({"errore": errore} if errore else {"risultato": risultato})}
    return PrevisionePronta.objects.create(azienda=azienda, chiave=chiave, dati=dati, modello="timestral-1",
                                           calcolata_il=calcolata_il or timezone.now())


def _salva_tutte(azienda, prodotto_pk=0):
    _salva(azienda, "vendite.fatturato_mese", {"storico": _storico(), "futuro": _futuro(), "totale": _totale(),
                                               "modello": "timestral-1", "affidabilita": FASCIA})
    _salva(azienda, "vendite.prodotti", {"periodi": ["09/2026", "10/2026", "11/2026"], "modello": "timestral-1",
                                         "gruppi": [_gruppo(prodotto_pk, "Monitor")], "esclusi": 2, "esclusi_unita": 3})
    _salva(azienda, "vendite.clienti", {"periodi": ["09/2026", "10/2026", "11/2026"], "modello": "timestral-1",
                                        "gruppi": [_gruppo(7, "Rossi Srl")], "esclusi": 0})


@pytest.fixture
def azienda(db):
    return Azienda.objects.get(pk=1)


@pytest.fixture
def servizi(monkeypatch):
    """Il servizio configurato; le chiamate vere sono vietate: la pagina non deve mai calcolare per un utente intero."""
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")
    cache.clear()

    def chiama(percorso, dati):
        raise AssertionError("la pagina non chiama il servizio")
    monkeypatch.setattr(servizio, "chiama", chiama)


@pytest.fixture
def capo(client):
    u = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(u)
    return u


def _utente(client, azienda, *permessi):
    u = User.objects.create_user("mario", "mario@example.com", "x")
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    for p in permessi:
        app, codename = p.split(".")
        u.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
    client.force_login(u)
    return User.objects.get(pk=u.pk)


def _riserva(slug, *aziende):
    Modulo.objects.update_or_create(slug=slug, defaults={"nome": slug.title()})[0].aziende.set(aziende)


def _pagina(client):
    return client.get(reverse("previsioni:pagina")).content.decode()


def _carta(client, chiave):
    r = client.get(reverse("previsioni:pronta", args=[chiave]))
    assert r.status_code == 200
    return r.content.decode()


def test_pagina_con_vendite_e_magazzino(client, capo, azienda, servizi):
    _salva_tutte(azienda)
    _riga(azienda, "Monitor", _giorni(10), magazzino="Negozio", esaurimento=_giorni(40), esaurimento_da=_giorni(30),
          esaurimento_a=_giorni(60))
    for i in range(11):
        _riga(azienda, f"Articolo {i:02d}", _giorni(20 + i), prodotto_pk=900 + i)
    StatoCalcolo.objects.create(azienda=azienda, cosa="vendite", errore="Il servizio non risponde",
                                ultimo_ok=timezone.make_aware(datetime.datetime(2026, 11, 20, 3)))
    html = _pagina(client)
    # Vendite: ogni previsione pronta si carica da sola, con HTMX
    for chiave in ("vendite.fatturato_mese", "vendite.prodotti", "vendite.clienti"):
        url = reverse("previsioni:pronta", args=[chiave])
        assert f'hx-get="{url}"' in html
    assert 'hx-trigger="load"' in html and "Calcolo in corso" in html
    assert "Vendite" in html and "Magazzino" in html
    assert "non aggiornata dal 20/11/2026" in html
    assert f'{reverse("previsioni:aggiorna")}?cosa=vendite' in html and f'{reverse("previsioni:aggiorna")}?cosa=magazzino' in html
    assert "csrfmiddlewaretoken" in html
    # Magazzino: i primi 10 per data di riordino, con la fascia, e il link alla vista
    assert "Monitor" in html and "Negozio" in html and "Articolo 08" in html and "Articolo 09" not in html
    assert f"{_giorni(30):%d/%m/%Y} – {_giorni(60):%d/%m/%Y}" in html
    assert reverse("previsioni:esaurimenti_lista") in html
    assert ATTRIBUZIONE in html


def test_carta_della_serie_singola(client, capo, azienda, servizi):
    _salva_tutte(azienda)
    html = _carta(client, "vendite.fatturato_mese")
    assert "<svg" in html and "Fascia 10-90 %" in html and "is-revealed" in html
    assert "09/2026" in html and "<strong>12</strong>" in html and "(8 – 16)" in html
    assert "Affidabilità: media" in html and "Storia: 14 mesi" in html
    assert "calcolata il" in html and ATTRIBUZIONE in html
    assert "Fatturato previsto per mese" in html or "Ordinato previsto per mese" in html


def test_carta_del_gruppo_con_esclusi(client, capo, azienda, servizi):
    _salva_tutte(azienda)
    html = _carta(client, "vendite.prodotti")
    assert "Totale previsto (10–90 %)" in html and "Monitor" in html and "39 (27 – 51)" in html
    assert "Affidabilità" in html and "ultima colonna" in html
    assert "3 righe in un'altra unità senza fattore, escluse" in html
    assert "2 gruppi esclusi per poca storia" in html
    assert ATTRIBUZIONE in html and "<svg" not in html
    assert "esclusi" not in _carta(client, "vendite.clienti")


def test_carta_senza_calcolo_o_con_errore(client, capo, azienda, servizi):
    html = _carta(client, "vendite.clienti")                       # mai calcolata
    assert pronte.NON_CALCOLATA in html and "<svg" not in html
    _salva(azienda, "vendite.fatturato_mese", errore="Nessun dato nei periodi passati.")
    assert "Nessun dato nei periodi passati." in _carta(client, "vendite.fatturato_mese")


def test_carta_con_errore_del_servizio_senza_traceback(client, capo, azienda, servizi, monkeypatch):
    monkeypatch.setattr(pronte, "dati_per", lambda request, chiave: {
        "chiave": chiave, "titolo": "Clienti", "spec": {}, "dati": None, "calcolata_il": None, "salvata": False,
        "errore": "Il servizio di previsione non risponde: riprova tra poco."})
    html = _carta(client, "vendite.clienti")
    assert "Il servizio di previsione non risponde: riprova tra poco." in html and "Traceback" not in html


def test_carta_calcolata_al_momento_dice_calcolata_ora(client, capo, azienda, servizi, monkeypatch):
    dati = {"storico": _storico(), "futuro": _futuro(), "totale": _totale(), "modello": "timestral-1",
            "affidabilita": FASCIA}
    monkeypatch.setattr(pronte, "dati_per", lambda request, chiave: {
        "chiave": chiave, "titolo": "Fatturato", "spec": {}, "dati": dati, "calcolata_il": timezone.now(),
        "salvata": False, "errore": ""})
    assert "calcolata ora" in _carta(client, "vendite.fatturato_mese")


def test_chiave_sconosciuta_o_non_visibile_404(client, capo, azienda, servizi):
    assert client.get(reverse("previsioni:pronta", args=["vendite.inventata"])).status_code == 404
    _riserva("vendite", Azienda.objects.create(nome="Altra"))              # Vendite non vale per l'azienda
    assert client.get(reverse("previsioni:pronta", args=["vendite.prodotti"])).status_code == 404


def test_senza_magazzino_niente_sezione(client, capo, azienda, servizi):
    _salva_tutte(azienda)
    _riserva("magazzino", Azienda.objects.create(nome="Altra"))
    r = client.get(reverse("previsioni:pagina"))
    assert r.status_code == 200
    html = r.content.decode()
    assert "prev-magazzino" not in html and "?cosa=magazzino" not in html
    assert reverse("previsioni:pronta", args=["vendite.prodotti"]) in html


def test_senza_vendite_ne_magazzino_testo_vuoto(client, capo, azienda, servizi):
    altra = Azienda.objects.create(nome="Altra")
    _riserva("vendite", altra)
    _riserva("magazzino", altra)
    r = client.get(reverse("previsioni:pagina"))
    assert r.status_code == 200
    assert "Nessuna previsione disponibile" in r.content.decode()


def test_senza_servizio_messaggio_e_ultime_salvate(client, capo, azienda):
    _salva_tutte(azienda)
    _riga(azienda, "Monitor", _giorni(10))
    html = _pagina(client)
    assert "Il servizio di previsione non è configurato: si vedono le ultime previsioni salvate." in html
    assert reverse("previsioni:aggiorna") not in html
    assert "Monitor" in html
    assert "39 (27 – 51)" in _carta(client, "vendite.prodotti")


def test_aggiorna_solo_con_il_permesso_di_modifica(client, azienda, servizi):
    _utente(client, azienda, "previsioni.view_previsionepronta", "vendite.view_ordinevendita", "vendite.view_rigavendita")
    html = _pagina(client)
    assert reverse("previsioni:pronta", args=["vendite.prodotti"]) in html and "?cosa=vendite" not in html


@pytest.mark.skipif(not apps.is_installed("grafici"), reason="serve Analisi")
def test_nuova_previsione_solo_con_analisi(client, capo, azienda, servizi):
    url = f'{reverse("grafici:costruttore")}?tipo=previsione'
    html = _pagina(client)
    assert "Nuova previsione" in html and url in html
    _riserva("grafici", Azienda.objects.create(nome="Altra"))               # Analisi non vale per l'azienda
    html = _pagina(client)
    assert "Nuova previsione" not in html.replace("«Nuova previsione»", "") and url not in html


@pytest.mark.skipif(not apps.is_installed("grafici"), reason="serve Analisi")
def test_nuova_previsione_vuole_il_permesso_di_creare_grafici(client, azienda, servizi):
    u = _utente(client, azienda, "previsioni.view_previsionepronta")
    assert f'{reverse("grafici:costruttore")}?tipo=previsione' not in _pagina(client)
    u.user_permissions.add(Permission.objects.get(content_type__app_label="grafici", codename="add_grafico"))
    client.force_login(User.objects.get(pk=u.pk))
    assert f'{reverse("grafici:costruttore")}?tipo=previsione' in _pagina(client)


def test_limite_senza_analisi_scritto_nella_pagina(client, capo, servizi):
    assert "senza Analisi il bottone «Nuova previsione» non compare" in _pagina(client)


def test_utente_senza_permesso_403(client, azienda):
    _utente(client, azienda)
    assert client.get(reverse("previsioni:pagina")).status_code == 403


def test_utente_solo_delle_pronte_niente_sezione_magazzino(client, azienda, servizi):
    _riga(azienda, "Monitor", _giorni(10), magazzino="Negozio")
    _utente(client, azienda, "previsioni.view_previsionepronta", "vendite.view_ordinevendita", "vendite.view_rigavendita")
    html = _pagina(client)
    assert "prev-magazzino" not in html and "Negozio" not in html


def test_basta_uno_dei_due_permessi(client, azienda, servizi):
    _utente(client, azienda, "previsioni.view_previsionearticolo")
    assert client.get(reverse("previsioni:pagina")).status_code == 200


def test_aggiorna_torna_alla_pagina(client, capo, azienda, servizi, monkeypatch):
    monkeypatch.setattr("previsioni.views.lavori.accoda", lambda *a, **k: None)
    r = client.post(f'{reverse("previsioni:aggiorna")}?cosa=vendite')
    assert r.status_code == 302 and r.url == reverse("previsioni:pagina")


def test_menu_previsioni(capo):
    from core.registry import modules
    voci = [v for a in modules.app_visibili(capo) if a["label"] == "Previsioni" for v in a["menu"]]
    assert voci[0]["url_name"] == "previsioni:pagina" and voci[0]["label"] == "Previsioni"


def test_widget_nella_libreria_della_dashboard(capo, azienda, servizi):
    _salva_tutte(azienda)
    catalogo, _ = dashboard.catalogo(richiesta_di(capo, azienda))
    w = {x["id"]: x for x in catalogo if x["id"].startswith("previsioni:")}
    assert list(w) == ["previsioni:vendite.fatturato_mese", "previsioni:vendite.prodotti", "previsioni:vendite.clienti"]
    assert w["previsioni:vendite.prodotti"]["su_richiesta"] is True and w["previsioni:vendite.prodotti"]["app"] == "Previsioni"
    assert w["previsioni:vendite.prodotti"]["template"] == "previsioni/_widget.html"
    caricato = w["previsioni:vendite.prodotti"]["carica"]()
    assert caricato["url"] == reverse("previsioni:pronta", args=["vendite.prodotti"])


def test_widget_nella_dashboard_si_carica_con_htmx(client, capo, azienda, servizi):
    from core.models import DashboardUtente
    DashboardUtente.objects.create(utente=capo, layout={"widget": [{"id": "previsioni:vendite.clienti", "w": 2}]})
    html = client.get(reverse("core:dashboard")).content.decode()
    assert reverse("previsioni:pronta", args=["vendite.clienti"]) in html and 'hx-trigger="load"' in html


def test_widget_solo_con_il_permesso(client, azienda, servizi):
    u = _utente(client, azienda)
    catalogo, _ = dashboard.catalogo(richiesta_di(u, azienda))
    assert not [x for x in catalogo if x["id"].startswith("previsioni:")]


# ---------- la scheda prodotto ----------

def _scheda(client, prodotto):
    return client.get(reverse("prodotti:prodotti_dettaglio", args=[prodotto.pk])).content.decode()


def test_vendite_previste_nella_scheda_prodotto(client, capo, azienda, servizi, prodotto):
    _salva_tutte(azienda, prodotto_pk=prodotto.pk)
    scheda = _scheda(client, prodotto)                              # nessuna riga di magazzino: il riquadro c'è lo stesso
    url = reverse("previsioni:prodotto_vendite", args=[prodotto.pk])
    assert f'hx-get="{url}"' in scheda and 'hx-trigger="load"' in scheda
    html = client.get(url).content.decode()
    assert "Vendite previste nei prossimi 3 mesi" in html and "39" in html and "27 – 51" in html
    assert "Affidabilità: media" in html and ATTRIBUZIONE in html


def test_prodotto_fuori_dai_primi_dieci(client, capo, azienda, servizi, prodotto):
    _salva_tutte(azienda, prodotto_pk=prodotto.pk + 1000)
    html = client.get(reverse("previsioni:prodotto_vendite", args=[prodotto.pk])).content.decode()
    assert "Vendite previste nei prossimi 3 mesi" in html and "non tra i 10 più venduti" in html


def test_scheda_prodotto_permessi_separati(client, azienda, servizi, prodotto):
    """Solo magazzino: niente riga di Vendite. Solo vendite: niente righe di magazzino, ma il riquadro c'è."""
    _riga(azienda, "Monitor", _giorni(10), prodotto_pk=prodotto.pk)
    _salva_tutte(azienda, prodotto_pk=prodotto.pk)
    u = _utente(client, azienda, "previsioni.view_previsionearticolo", "magazzino.view_movimento", "prodotti.view_prodotto")
    html = _scheda(client, prodotto)
    assert "Finisce" in html or "Riordina" in html
    assert reverse("previsioni:prodotto_vendite", args=[prodotto.pk]) not in html
    assert client.get(reverse("previsioni:prodotto_vendite", args=[prodotto.pk])).status_code == 404
    for p in ("previsioni.view_previsionepronta", "vendite.view_ordinevendita", "vendite.view_rigavendita"):
        app, codename = p.split(".")
        u.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
    u.user_permissions.remove(Permission.objects.get(codename="view_previsionearticolo"))
    client.force_login(User.objects.get(pk=u.pk))
    html = _scheda(client, prodotto)
    assert reverse("previsioni:prodotto_vendite", args=[prodotto.pk]) in html and "Finisce" not in html
    assert PrevisioneArticolo.objects.count() == 1
