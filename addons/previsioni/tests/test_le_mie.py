"""«Le mie previsioni» nella pagina Previsioni: elenco da chat e da Analisi, cerca e filtri, rinomina, etichetta."""
import re

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core import parametri
from core.models import Azienda, Modulo
from previsioni import pronte
from previsioni.models import EtichettaPrevisione

pytestmark = [pytest.mark.django_db,
              pytest.mark.skipif(not (apps.is_installed("ai") and apps.is_installed("grafici")),
                                 reason="serve l'Assistente AI e Analisi")]

if apps.is_installed("ai") and apps.is_installed("grafici"):
    from ai.models import Artifact
    from grafici.models import Grafico

SEZIONE = 'id="prev-mie"'


@pytest.fixture(autouse=True)
def servizio_acceso():
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")


@pytest.fixture
def azienda(db):
    return Azienda.objects.get(pk=1)


@pytest.fixture
def capo(client):
    u = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(u)
    return u


@pytest.fixture
def altro(db):
    return User.objects.create_user("altro", "altro@example.com", "x")


def _artifact(utente, azienda, titolo="Fatturato dei prossimi mesi", tipo="grafico", salvato=False, **spec):
    spec = {"grafico": "previsione", "per": "mese", **(spec or {"misura_aziendale": "fatturazione.fatturato"})}
    return Artifact.objects.create(utente=utente, azienda=azienda, tipo=tipo, titolo=titolo, spec=spec, salvato=salvato)


def _grafico(utente, titolo="Righe vendute", tipo=Grafico.PREVISIONE if apps.is_installed("grafici") else "", **spec):
    spec = spec or {"vista": "vendite.righe_vendute", "data": "data", "per": "settimana", "orizzonte": 3}
    return Grafico.objects.create(utente=utente, titolo=titolo, tipo=tipo, spec=spec)


def _pagina(client):
    r = client.get(reverse("previsioni:pagina"))
    assert r.status_code == 200
    return r.content.decode()


def _scheda(html, titolo):
    """Il tag della riga con quel titolo (con i suoi data-*)."""
    m = re.search(r'<tr[^>]*data-cerca="[^"]*"[^>]*>(?:(?!</tr>).)*?' + re.escape(titolo), html, re.S)
    assert m, f"{titolo} non c'è nella sezione"
    return re.findall(r'<tr[^>]*data-cerca="[^"]*"[^>]*>', html[:m.end()])[-1]


# ---------- l'elenco ----------

def test_elenca_chat_e_analisi_con_argomento_e_tipo(client, capo, azienda):
    a = _artifact(capo, azienda)
    b = _artifact(capo, azienda, "Primi prodotti", tipo="tabella", vista="vendite.righe_vendute", raggruppa="prodotto", primi=5)
    g = _grafico(capo)
    html = _pagina(client)
    assert SEZIONE in html
    assert "Fatturato dei prossimi mesi" in html and "Primi prodotti" in html and "Righe vendute" in html
    assert reverse("ai:artifact", args=[a.pk]) in html and reverse("ai:artifact", args=[b.pk]) in html
    assert reverse("grafici:grafico", args=[g.pk]) in html
    riga = _scheda(html, "Fatturato dei prossimi mesi")
    assert 'data-origine="chat"' in riga and 'data-argomento="Fatturazione"' in riga and 'data-tipo="andamento"' in riga
    riga = _scheda(html, "Primi prodotti")
    assert 'data-tipo="classifica"' in riga and 'data-argomento="Vendite"' in riga
    assert "Classifica (primi 5)" in html
    riga = _scheda(html, "Righe vendute")
    assert 'data-origine="analisi"' in riga and 'data-argomento="Vendite"' in riga
    assert "per settimana" in html


def test_argomento_che_non_si_ricava_e_altro(client, capo, azienda):
    _artifact(capo, azienda, "Senza origine", vista="core.lavoro")
    assert 'data-argomento="Altro"' in _scheda(_pagina(client), "Senza origine")


def test_non_elenca_quelle_degli_altri_ne_altre_aziende_ne_quello_che_non_e_previsione(client, capo, altro, azienda):
    altra = Azienda.objects.create(nome="Altra Srl")
    _artifact(altro, azienda, "Di un altro utente")
    _artifact(capo, altra, "Di un'altra azienda")
    _artifact(capo, azienda, "Un grafico qualunque", grafico="barre")
    Artifact.objects.create(utente=capo, azienda=azienda, tipo="grafico", titolo="Senza spec", spec={})
    _grafico(altro, "Grafico di un altro")
    _grafico(capo, "Una barra", tipo=Grafico.BARRE, vista="vendite.righe_vendute", per="mese")
    _artifact(capo, azienda, "La mia")
    html = _pagina(client)
    assert "La mia" in html
    for titolo in ("Di un altro utente", "Di un&#x27;altra azienda", "Un grafico qualunque", "Senza spec",
                   "Grafico di un altro", "Una barra"):
        assert titolo not in html


def test_ordine_dal_piu_recente(client, capo, azienda):
    _artifact(capo, azienda, "Prima")
    _grafico(capo, "Seconda")
    _artifact(capo, azienda, "Terza")
    html = _pagina(client)
    assert html.index("Terza") < html.index("Seconda") < html.index("Prima")


def test_senza_previsioni_il_testo_breve(client, capo, azienda):
    html = _pagina(client)
    assert SEZIONE in html and "Non hai ancora fatto previsioni" in html and "Nuova previsione" in html


def test_senza_ai_e_senza_grafici_la_sezione_non_c_e(client, capo, azienda, monkeypatch):
    _artifact(capo, azienda)
    _grafico(capo)
    vera = pronte.app_attiva
    monkeypatch.setattr(pronte, "app_attiva", lambda slug, *a, **k: slug not in ("ai", "grafici") and vera(slug, *a, **k))
    html = _pagina(client)
    assert SEZIONE not in html and "Le mie previsioni" not in html


def test_con_una_sola_fonte_attiva(client, capo, azienda, monkeypatch):
    _artifact(capo, azienda, "Dalla chat")
    _grafico(capo, "Da Analisi")
    vera = pronte.app_attiva
    monkeypatch.setattr(pronte, "app_attiva", lambda slug, *a, **k: slug != "grafici" and vera(slug, *a, **k))
    html = _pagina(client)
    assert "Dalla chat" in html and "Da Analisi" not in html


# ---------- rinomina ----------

def test_rinomina_cambia_il_titolo_dell_oggetto_d_origine(client, capo, azienda):
    a, g = _artifact(capo, azienda), _grafico(capo)
    r = client.post(reverse("previsioni:rinomina", args=["chat", a.pk]), {"titolo": "  Fatturato 2027  "})
    assert r.status_code in (200, 302)
    a.refresh_from_db()
    assert a.titolo == "Fatturato 2027"
    r = client.post(reverse("previsioni:rinomina", args=["analisi", g.pk]), {"titolo": "Righe 2027"})
    assert r.status_code in (200, 302)
    g.refresh_from_db()
    assert g.titolo == "Righe 2027"
    assert "Fatturato 2027" in _pagina(client)


def test_rinomina_htmx_risponde_con_la_riga(client, capo, azienda):
    a = _artifact(capo, azienda)
    r = client.post(reverse("previsioni:rinomina", args=["chat", a.pk]), {"titolo": "Nuovo nome"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200
    assert "Nuovo nome" in r.content.decode() and "<html" not in r.content.decode()


def test_rinomina_di_un_altro_utente_e_404(client, capo, altro, azienda):
    a, g = _artifact(altro, azienda), _grafico(altro)
    assert client.post(reverse("previsioni:rinomina", args=["chat", a.pk]), {"titolo": "x"}).status_code == 404
    assert client.post(reverse("previsioni:rinomina", args=["analisi", g.pk]), {"titolo": "x"}).status_code == 404
    a.refresh_from_db(), g.refresh_from_db()
    assert a.titolo != "x" and g.titolo != "x"


def test_rinomina_solo_previsioni(client, capo, azienda):
    a = _artifact(capo, azienda, grafico="barre")
    g = _grafico(capo, tipo=Grafico.BARRE)
    assert client.post(reverse("previsioni:rinomina", args=["chat", a.pk]), {"titolo": "x"}).status_code == 404
    assert client.post(reverse("previsioni:rinomina", args=["analisi", g.pk]), {"titolo": "x"}).status_code == 404


def test_rinomina_titolo_vuoto_o_troppo_lungo_400(client, capo, azienda):
    a = _artifact(capo, azienda)
    url = reverse("previsioni:rinomina", args=["chat", a.pk])
    assert client.post(url, {"titolo": "   "}).status_code == 400
    assert client.post(url, {"titolo": "x" * 201}).status_code == 400
    a.refresh_from_db()
    assert a.titolo == "Fatturato dei prossimi mesi"


def test_rinomina_get_non_ammesso_e_origine_sconosciuta(client, capo, azienda):
    a = _artifact(capo, azienda)
    assert client.get(reverse("previsioni:rinomina", args=["chat", a.pk])).status_code == 405
    assert client.post(reverse("previsioni:rinomina", args=["altro", a.pk]), {"titolo": "x"}).status_code == 404


# ---------- etichetta ----------

def test_etichetta_imposta_cambia_toglie(client, capo, azienda):
    a = _artifact(capo, azienda)
    url = reverse("previsioni:etichetta", args=["chat", a.pk])
    assert client.post(url, {"etichetta": " Budget "}).status_code in (200, 302)
    e = EtichettaPrevisione.objects.get()
    assert (e.utente, e.origine, e.oggetto_pk, e.etichetta, e.azienda) == (capo, "chat", a.pk, "Budget", azienda)
    client.post(url, {"etichetta": "Scorte"})
    assert EtichettaPrevisione.objects.get().etichetta == "Scorte"
    client.post(url, {"etichetta": ""})
    assert not EtichettaPrevisione.objects.exists()


def test_etichetta_troppo_lunga_400(client, capo, azienda):
    a = _artifact(capo, azienda)
    assert client.post(reverse("previsioni:etichetta", args=["chat", a.pk]), {"etichetta": "x" * 61}).status_code == 400


def test_etichetta_di_un_altro_utente_e_404(client, capo, altro, azienda):
    a = _artifact(altro, azienda)
    assert client.post(reverse("previsioni:etichetta", args=["chat", a.pk]), {"etichetta": "x"}).status_code == 404
    assert not EtichettaPrevisione.objects.exists()


def test_etichetta_get_non_ammesso(client, capo, azienda):
    a = _artifact(capo, azienda)
    assert client.get(reverse("previsioni:etichetta", args=["chat", a.pk])).status_code == 405


def test_etichetta_nell_elenco_nel_filtro_e_nel_cerca(client, capo, altro, azienda):
    a, g = _artifact(capo, azienda), _grafico(capo)
    client.post(reverse("previsioni:etichetta", args=["chat", a.pk]), {"etichetta": "Budget"})
    EtichettaPrevisione.objects.create(utente=altro, azienda=azienda, origine="chat", oggetto_pk=a.pk, etichetta="Segreta")
    html = _pagina(client)
    riga = _scheda(html, "Fatturato dei prossimi mesi")
    assert 'data-etichetta="Budget"' in riga and "budget" in riga.lower().split("data-cerca=")[1]
    assert '<option value="Budget"' in html and "Segreta" not in html
    assert '<datalist' in html and '<option value="Budget"></option>' in html


def test_etichetta_di_un_oggetto_che_non_esiste_piu_non_compare(client, capo, azienda):
    EtichettaPrevisione.objects.create(utente=capo, azienda=azienda, origine="chat", oggetto_pk=9999, etichetta="Fantasma")
    _artifact(capo, azienda)
    assert "Fantasma" not in _pagina(client)


def test_etichette_di_oggetti_spariti_si_cancellano_quando_si_incontrano(client, capo, azienda):
    a = _artifact(capo, azienda)
    altra = Azienda.objects.create(nome="Altra Srl")
    di_altra = _artifact(capo, altra, "Nell'altra azienda")       # esiste: l'etichetta resta
    fantasma = EtichettaPrevisione.objects.create(utente=capo, azienda=azienda, origine="chat", oggetto_pk=9999, etichetta="Fantasma")
    fantasma_g = EtichettaPrevisione.objects.create(utente=capo, azienda=azienda, origine="analisi", oggetto_pk=9998, etichetta="Fantasma2")
    viva = EtichettaPrevisione.objects.create(utente=capo, azienda=azienda, origine="chat", oggetto_pk=a.pk, etichetta="Viva")
    resta = EtichettaPrevisione.objects.create(utente=capo, azienda=altra, origine="chat", oggetto_pk=di_altra.pk, etichetta="Resta")
    _pagina(client)
    assert set(EtichettaPrevisione.objects.values_list("pk", flat=True)) == {viva.pk, resta.pk}
    assert fantasma.pk and fantasma_g.pk


# ---------- salvate ----------

def test_salvata_e_un_attributo_e_un_filtro(client, capo, azienda):
    _artifact(capo, azienda, "Tenuta", salvato=True)
    _artifact(capo, azienda, "Di passaggio", salvato=False)
    _grafico(capo, "Di Analisi")
    html = _pagina(client)
    assert "Tenuta" in html and "Di passaggio" in html              # si elencano tutte, salvate o no
    assert 'data-salvata="si"' in _scheda(html, "Tenuta")
    assert 'data-salvata="no"' in _scheda(html, "Di passaggio")
    assert 'data-salvata="si"' in _scheda(html, "Di Analisi")      # Analisi: salvata per definizione
    righe = {t: r for r in re.findall(r"<tr .*?</tr>", html, re.S) for t in ("Tenuta", "Di passaggio") if f">{t}</a>" in r}
    assert "prev-salvata" in righe["Tenuta"] and "prev-salvata" not in righe["Di passaggio"]
    assert 'id="prev-salvate"' in html and "Solo salvate" in html


# ---------- Analisi: serve il permesso ----------

def _utente_senza_analisi(client, azienda, *permessi):
    u = User.objects.create_user("mario", "mario@example.com", "x")
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    for p in ("previsioni.view_previsionepronta",) + permessi:
        app, codename = p.split(".")
        u.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
    client.force_login(u)
    return u


def test_analisi_serve_view_grafico(client, azienda):
    u = _utente_senza_analisi(client, azienda)
    g, a = _grafico(u, "Da Analisi"), _artifact(u, azienda, "Dalla chat")
    html = _pagina(client)
    assert "Dalla chat" in html and "Da Analisi" not in html
    assert client.post(reverse("previsioni:rinomina", args=["analisi", g.pk]), {"titolo": "x"}).status_code == 404
    assert client.post(reverse("previsioni:etichetta", args=["analisi", g.pk]), {"etichetta": "x"}).status_code == 404
    u.user_permissions.add(Permission.objects.get(content_type__app_label="grafici", codename="view_grafico"))
    client.force_login(User.objects.get(pk=u.pk))
    assert "Da Analisi" in _pagina(client)
    assert client.post(reverse("previsioni:rinomina", args=["analisi", g.pk]), {"titolo": "x"}).status_code == 302


# ---------- varie ----------

def test_rinomina_di_un_grafico_aggiorna_modificato(client, capo):
    import datetime
    from django.utils import timezone
    g = _grafico(capo)
    vecchio = timezone.now() - datetime.timedelta(days=30)
    Grafico.objects.filter(pk=g.pk).update(modificato=vecchio)
    client.post(reverse("previsioni:rinomina", args=["analisi", g.pk]), {"titolo": "Nuovo"})
    g.refresh_from_db()
    assert g.modificato > vecchio + datetime.timedelta(days=29)


def test_il_messaggio_senza_previsioni_possibili_non_c_e_con_la_sezione(client, capo, azienda):
    html = _pagina(client)
    assert SEZIONE in html and "servono Vendite o Magazzino" not in html


def test_la_riga_ha_i_ganci_per_l_errore_e_la_tendina_etichette_c_e_sempre(client, capo, azienda):
    _artifact(capo, azienda)
    html = _pagina(client)
    assert 'data-filtro="etichetta"' in html and 'id="prev-etichette"' in html and "prev-errore" in html


# ---------- barra ----------

def test_la_barra_ha_solo_i_valori_presenti(client, capo, azienda):
    _artifact(capo, azienda)
    _grafico(capo)
    html = _pagina(client)
    assert 'id="prev-cerca"' in html and "mk-barra" in html
    for valore in ("Fatturazione", "Vendite", "Andamento", "Chat", "Analisi"):
        assert f'<option value="{valore}"' in html
    assert '<option value="Classifica"' not in html and '<option value="Magazzino"' not in html
    assert "Nessuna previsione con questi filtri" in html


def test_il_cerca_contiene_titolo_etichetta_e_argomento(client, capo, azienda):
    a = _artifact(capo, azienda, "Fatturato ottimista")
    client.post(reverse("previsioni:etichetta", args=["chat", a.pk]), {"etichetta": "Budget"})
    riga = _scheda(_pagina(client), "Fatturato ottimista")
    cerca = re.search(r'data-cerca="([^"]*)"', riga).group(1).lower()
    assert "fatturato ottimista" in cerca and "budget" in cerca and "fatturazione" in cerca


def test_senza_vendite_e_magazzino_ma_con_la_sezione_niente_messaggio_vuota(client, capo, azienda):
    """`vuota` è vero (Vendite e Magazzino riservati a un'altra azienda) ma «Le mie previsioni» c'è: il testo «servono
    Vendite o Magazzino» non deve comparire."""
    altra = Azienda.objects.create(nome="Altra Srl")
    for slug in ("vendite", "magazzino"):
        Modulo.objects.update_or_create(slug=slug, defaults={"nome": slug.title()})[0].aziende.set([altra])
    _artifact(capo, azienda, "Una mia previsione")
    html = _pagina(client)
    assert SEZIONE in html and "Una mia previsione" in html
    assert "Nessuna previsione disponibile" not in html and "servono Vendite o Magazzino" not in html
