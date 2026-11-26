"""Le previsioni solo con il modulo installato, attivo e in licenza (e con il servizio configurato)."""
import datetime

import pytest
from django.apps import apps
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from core import licenza, parametri
from core.models import Azienda, Modulo
from core.viste.interroga import richiesta_di
from previsioni import pronte, servizio

pytestmark = pytest.mark.django_db
serve_ai = pytest.mark.skipif(not apps.is_installed("ai"), reason="serve l'Assistente AI")
serve_analisi = pytest.mark.skipif(not apps.is_installed("grafici"), reason="serve Analisi")

if apps.is_installed("ai"):
    from ai import artifact, strumenti
    from ai.models import Artifact, Conversazione

    SPEC = {"tipo": Artifact.GRAFICO, "grafico": "previsione", "vista": "core.lavoro", "data": "creato", "misura": "count",
            "per": "mese", "orizzonte": 3}
if apps.is_installed("grafici"):
    from grafici import motore as motore_grafici
    from grafici.models import Grafico


@pytest.fixture
def capo(client):
    u = User.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(u)
    return u


@pytest.fixture
def con_url():
    parametri.scrivi("previsioni.url_servizio", "http://forecast:8080")


def _contesto(capo):
    return strumenti.Contesto(utente=capo, azienda=Azienda.objects.get(pk=1),
                              conversazione=Conversazione.objects.create(utente=capo))


def _senza_licenza(monkeypatch):
    monkeypatch.setattr(licenza, "ammesso", lambda slug: slug != "previsioni")


def _non_installato(monkeypatch):
    originale = apps.is_installed
    monkeypatch.setattr(apps, "is_installed", lambda nome: False if nome == "previsioni" else originale(nome))
    monkeypatch.setattr(servizio, "attivo", lambda *a, **k: False)
    monkeypatch.setattr(servizio, "abilitato", lambda *a, **k: False)


def _spento_a_mano():
    Modulo.objects.update_or_create(slug="previsioni", defaults={"nome": "Previsioni", "disattivato": True})


def _riservato_ad_altri():
    altra = Azienda.objects.create(nome="Altra Srl")
    Modulo.objects.update_or_create(slug="previsioni", defaults={"nome": "Previsioni"})[0].aziende.set([altra])


@serve_analisi
def test_senza_licenza_niente_tipo_previsione_nel_costruttore(client, capo, con_url, monkeypatch):
    assert 'value="previsione"' in client.get(reverse("grafici:costruttore")).content.decode()
    _senza_licenza(monkeypatch)
    assert 'value="previsione"' not in client.get(reverse("grafici:costruttore")).content.decode()
    assert motore_grafici.previsioni_disponibili() is False


@serve_ai
def test_senza_licenza_niente_strumento_previsione(capo, con_url, monkeypatch):
    assert "previsione" in {s.nome for s in strumenti.disponibili(capo)}
    _senza_licenza(monkeypatch)
    assert "previsione" not in {s.nome for s in strumenti.disponibili(capo)}


@serve_ai
@serve_analisi
def test_modulo_spento_a_mano_niente_strumento_ne_tipo_ne_calcolo(client, capo, con_url):
    """Un vero Modulo.disattivato (pagina Moduli): il kernel nasconde pagine, menu e cron; anche Analisi, la chat e le
    previsioni pronte lo vedono spento."""
    azienda = Azienda.objects.get(pk=1)
    assert servizio.abilitato(azienda, capo) and pronte.app_attiva("previsioni", azienda, capo)
    _spento_a_mano()
    assert servizio.abilitato() is False and servizio.attivo() is False
    assert pronte.app_attiva("previsioni", azienda, capo) is False
    assert "previsione" not in {s.nome for s in strumenti.disponibili(capo)}
    assert motore_grafici.previsioni_disponibili() is False
    assert 'value="previsione"' not in client.get(reverse("grafici:costruttore")).content.decode()
    with pytest.raises(motore_grafici.ErroreInterrogazione, match="Serve il modulo Previsioni."):
        motore_grafici._previsione(SPEC, richiesta_di(capo, azienda))
    with pytest.raises(strumenti.ErroreStrumento, match="Serve il modulo Previsioni."):
        artifact._calcola(SPEC, _contesto(capo))


@serve_ai
@serve_analisi
def test_modulo_riservato_a_un_altra_azienda(client, capo, con_url):
    """Modulo.aziende: per l'azienda corrente le previsioni non ci sono, né in Analisi né nella chat."""
    azienda = Azienda.objects.get(pk=1)
    _riservato_ad_altri()
    assert servizio.abilitato() is True                              # senza azienda (il lavoro della notte) non limita
    assert servizio.abilitato(azienda, capo) is False and servizio.attivo(azienda, capo) is False
    assert pronte.app_attiva("previsioni", azienda, capo) is False
    request = richiesta_di(capo, azienda)
    assert motore_grafici.previsioni_disponibili(request) is False
    assert 'value="previsione"' not in client.get(reverse("grafici:costruttore")).content.decode()
    with pytest.raises(motore_grafici.ErroreInterrogazione, match="Serve il modulo Previsioni."):
        motore_grafici._previsione(SPEC, request)
    contesto = _contesto(capo)
    with pytest.raises(strumenti.ErroreStrumento, match="Serve il modulo Previsioni."):
        artifact._calcola(SPEC, contesto)
    from previsioni import ai as ai_previsioni
    with pytest.raises(strumenti.ErroreStrumento, match="Serve il modulo Previsioni."):
        ai_previsioni.previsione(contesto, "core.lavoro", "creato")
    a = Artifact(spec=SPEC, titolo="x", azienda=azienda, utente=capo,
                 dati={"storico": [["ott 2026", 1.0]], "futuro": [["nov 2026", 1.0, 2.0, 3.0]]})
    assert artifact.svg_di(a) == ""


@serve_analisi
def test_grafico_previsione_salvato_senza_modulo_mostra_il_messaggio(client, capo, con_url, monkeypatch):
    g = Grafico.objects.create(utente=capo, titolo="Lavori previsti", tipo=Grafico.PREVISIONE,
                               spec={"vista": "core.lavoro", "misura": "count", "data": "creato", "per": "mese", "orizzonte": 3})
    _senza_licenza(monkeypatch)
    with pytest.raises(motore_grafici.ErroreInterrogazione, match="Serve il modulo Previsioni."):
        motore_grafici._previsione(g.spec, None)
    _non_installato(monkeypatch)
    with pytest.raises(motore_grafici.ErroreInterrogazione, match="Serve il modulo Previsioni."):
        motore_grafici._previsione(g.spec, None)
    assert motore_grafici.previsioni_disponibili() is False


@serve_ai
def test_chat_senza_modulo_attivo_o_installato(capo, con_url, monkeypatch):
    contesto = _contesto(capo)
    _senza_licenza(monkeypatch)
    with pytest.raises(strumenti.ErroreStrumento, match="Serve il modulo Previsioni."):
        artifact._calcola(SPEC, contesto)
    a = Artifact(spec=SPEC, titolo="x", dati={"storico": [], "futuro": []})
    assert artifact.svg_di(a) == ""
    _non_installato(monkeypatch)
    with pytest.raises(strumenti.ErroreStrumento, match="Serve il modulo Previsioni."):
        artifact._calcola(SPEC, contesto)
    assert artifact.svg_di(a) == ""


@serve_ai
@serve_analisi
def test_con_licenza_tutto_come_prima(client, capo, con_url, monkeypatch):
    from previsioni.tests.test_motore import _finta_risposta
    monkeypatch.setattr(servizio, "chiama", lambda percorso, dati: _finta_risposta(dati))
    from django.utils import timezone

    from core.models import Lavoro
    from previsioni.motore import avanti, inizio
    primo = inizio(timezone.localdate(), "mese")
    for n in range(1, 7):
        lavoro = Lavoro.objects.create(funzione="prova.lavoro")
        Lavoro.objects.filter(pk=lavoro.pk).update(creato=timezone.make_aware(
            timezone.datetime.combine(avanti(primo, "mese", -n), timezone.datetime.min.time())))
    assert servizio.attivo() and motore_grafici.previsioni_disponibili()
    assert 'value="previsione"' in client.get(reverse("grafici:costruttore")).content.decode()
    assert "previsione" in {s.nome for s in strumenti.disponibili(capo)}
    dati = artifact._calcola(SPEC, _contesto(capo))
    assert dati["modello"] == "finto-timestral"


@serve_ai
def test_la_vista_inesistente_ha_un_messaggio_neutro(capo, rf):
    from previsioni import motore
    richiesta = strumenti.richiesta.per(_contesto(capo))
    with pytest.raises(servizio.ErrorePrevisione) as e:
        motore.vista_accessibile(richiesta, "core.nessuna")
    assert "elenco_viste" not in str(e.value)


# ---------- senza il modulo il messaggio prende il posto dei dati salvati (spec, «11. Senza compatibilità») ----------

VECCHI = {"storico": [["ott 2026", 5.0]], "futuro": [["dic 2026", 1.0, 7777.0, 9999.0]],
          "totale": {"basso_10": 1.0, "mediana": 7777.0, "alto_90": 9999.0}, "modello": "vecchio-modello"}


def _grafico_salvato(capo, **altro):
    return Grafico.objects.create(
        utente=capo, titolo="Lavori previsti", tipo=Grafico.PREVISIONE,
        spec={"vista": "core.lavoro", "misura": "count", "data": "creato", "per": "mese", "orizzonte": 3},
        dati=VECCHI, **altro)


def _vede_i_vecchi(client, capo, g):
    """(scheda, «Apri in grande», CSV) del grafico salvato, come le vede il proprietario."""
    request = richiesta_di(capo, Azienda.objects.get(pk=1))
    scheda = render_to_string("grafici/_widget.html", {"w": motore_grafici.widget_salvato(g, request), "request": request})
    grande = client.get(reverse("grafici:grafico", args=[g.pk])).content.decode()
    csv = client.get(reverse("grafici:grafico_csv", args=[g.pk]))
    return scheda, grande, csv


@serve_analisi
@pytest.mark.parametrize("fresca", [True, False])
@pytest.mark.parametrize("come", ["licenza", "spento", "altra_azienda"])
def test_grafico_previsione_salvato_senza_modulo_non_mostra_i_numeri_vecchi(client, capo, con_url, monkeypatch, come,
                                                                             fresca):
    adesso = timezone.now()
    g = _grafico_salvato(capo, aggiornato=adesso if fresca else adesso - datetime.timedelta(days=2))
    {"licenza": lambda: _senza_licenza(monkeypatch), "spento": _spento_a_mano, "altra_azienda": _riservato_ad_altri}[come]()
    scheda, grande, csv = _vede_i_vecchi(client, capo, g)
    assert "7777" not in scheda and "Serve il modulo Previsioni." in scheda
    assert "7777" not in grande and "Serve il modulo Previsioni." in grande
    assert csv.status_code == 409 and csv.content.decode() == "Serve il modulo Previsioni."


@serve_analisi
def test_grafico_previsione_senza_indirizzo_e_un_guasto_restano_i_dati_di_prima(client, capo, monkeypatch):
    """Senza l'URL del servizio il modulo c'è (licenza, acceso): vale la regola del guasto, i dati salvati restano."""
    g = _grafico_salvato(capo, aggiornato=timezone.now() - datetime.timedelta(days=2))
    scheda, grande, csv = _vede_i_vecchi(client, capo, g)
    assert "7777" in scheda and "an-errore" in scheda               # il motivo del guasto accanto ai numeri di prima
    assert "7777" in grande and csv.status_code == 200


@serve_ai
@pytest.mark.parametrize("come", ["licenza", "spento", "altra_azienda"])
def test_previsione_della_chat_senza_modulo_niente_istantanea(client, capo, con_url, monkeypatch, come):
    azienda = Azienda.objects.get(pk=1)
    conversazione = Conversazione.objects.create(utente=capo)
    tabella = Artifact.objects.create(
        conversazione=conversazione, utente=capo, azienda=azienda, tipo=Artifact.TABELLA, titolo="Per funzione",
        spec={**SPEC, "tipo": Artifact.TABELLA, "raggruppa": "funzione", "primi": 3},
        dati={"colonne": ["Gruppo", "Totale previsto (10–90 %)"], "righe": [["prova.f0", "7777 (1 – 9999)"]],
              "modello": "vecchio-modello"})
    grafico = Artifact.objects.create(conversazione=conversazione, utente=capo, azienda=azienda, tipo=Artifact.GRAFICO,
                                      titolo="Lavori", spec=SPEC, dati=VECCHI)
    {"licenza": lambda: _senza_licenza(monkeypatch), "spento": _spento_a_mano, "altra_azienda": _riservato_ad_altri}[come]()
    for a in (tabella, grafico):
        chat = client.post(reverse("ai:salva_artifact", args=[a.pk]), HTTP_HX_REQUEST="true").content.decode()
        assert "7777" not in chat and "Serve il modulo Previsioni." in chat
        csv = client.get(reverse("ai:artifact_csv", args=[a.pk]))
        assert csv.status_code == 409 and csv.content.decode() == "Serve il modulo Previsioni."
