"""Le previsioni solo con il modulo installato, attivo e in licenza (e con il servizio configurato)."""
import pytest
from django.apps import apps
from django.contrib.auth.models import User
from django.urls import reverse

from core import licenza, parametri
from core.models import Azienda
from previsioni import servizio

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
    monkeypatch.setattr(servizio, "attivo", lambda: False)
    monkeypatch.setattr(servizio, "abilitato", lambda: False)


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
def test_modulo_disattivato_niente_strumento_ne_tipo(capo, con_url, monkeypatch):
    from core.registry import modules
    originale = modules.manifests_attivi
    monkeypatch.setattr(modules, "manifests_attivi",
                        lambda *a, **k: {s: m for s, m in originale(*a, **k).items() if s != "previsioni"})
    assert "previsione" not in {s.nome for s in strumenti.disponibili(capo)}
    assert motore_grafici.previsioni_disponibili() is False


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
