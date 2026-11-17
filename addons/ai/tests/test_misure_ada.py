"""Le misure aziendali nell'assistente: lo strumento misura e misura_aziendale in grafici e previsioni."""
import pytest
from django.contrib.auth.models import User

from ai import artifact, specialisti, strumenti
from ai.models import Conversazione
from ai.strumenti import misure as strumento_misure
from core import misure
from core.registry import modules
from core.viste.interroga import richiesta_di
from fatturazione.tests.test_fatturazione import OGGI, _fattura, scena  # noqa: F401  (fixture)


@pytest.fixture
def contesto(scena):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    return strumenti.Contesto(utente=capo, azienda=scena[0], conversazione=Conversazione.objects.create(utente=capo))


def _mesi_fa(n):
    return specialisti.avanti(OGGI.replace(day=1), "mese", -n).replace(day=10)


def test_strumento_misura_fatturato(scena, contesto):
    azienda, cliente, monitor, _ = scena
    _fattura(azienda, cliente, [(monitor, "5")], stato="emessa")
    _fattura(azienda, cliente, [(monitor, "1")], stato="emessa", tipo="TD04")
    r = strumento_misure.misura(contesto, nome="fatturazione.fatturato", periodo="anno")
    assert r["valore"] == 800 == misure.calcola("fatturazione.fatturato", richiesta_di(contesto.utente), periodo="anno")["valore"]
    assert "note di credito" in r["definizione"] and "definizione" in r["nota"]


def test_grafico_con_misura_aziendale_si_ricalcola(scena, contesto):
    azienda, cliente, monitor, _ = scena
    _fattura(azienda, cliente, [(monitor, "5")], stato="emessa")
    r = artifact.grafico(contesto, misura_aziendale="fatturazione.fatturato", per="cliente", periodo="anno", tipo="torta")
    assert r["totale"] == 1000 and r["serie"] == [("Rossi Srl", 1000)]
    a = artifact.Artifact.objects.get(pk=r["artifact"])
    _fattura(azienda, cliente, [(monitor, "1")], stato="emessa")
    assert artifact.ricalcola(a)["totale"] == 1200


def test_periodo_relativo_resta_relativo(scena, contesto):
    relativo = artifact.grafico(contesto, misura_aziendale="fatturazione.fatturato", per="mese", periodo="anno")
    a = artifact.Artifact.objects.get(pk=relativo["artifact"])
    assert a.spec["periodo"] == "anno" and "dal" not in a.spec
    assert a.titolo == "Fatturato dell'anno in corso"
    fisso = artifact.grafico(contesto, misura_aziendale="fatturazione.fatturato", per="mese",
                             dal=f"{OGGI.year}-01-01", al=f"{OGGI.year}-12-31")
    b = artifact.Artifact.objects.get(pk=fisso["artifact"])
    assert (b.spec["dal"], b.spec["al"]) == (f"{OGGI.year}-01-01", f"{OGGI.year}-12-31") and "periodo" not in b.spec
    assert b.titolo == f"Fatturato {OGGI.year}"


def test_previsione_con_misura_aziendale(scena, contesto, monkeypatch):
    azienda, cliente, monitor, _ = scena
    inviate = []

    def chiama(chiave, percorso, dati, nome):
        inviate.append(dati["series"][0]["values"])
        h = dati["horizon"]
        return {"model": "finto", "forecasts": [{"id": "serie", "quantiles": {"0.1": [1] * h, "0.5": [2] * h, "0.9": [3] * h}}]}
    monkeypatch.setattr(specialisti, "chiama", chiama)
    for n in range(1, 9):
        _fattura(azienda, cliente, [(monitor, "1")], stato="emessa", data=_mesi_fa(n))       # 200 al mese
    _fattura(azienda, cliente, [(monitor, "1")], stato="emessa", tipo="TD04", data=_mesi_fa(1))   # −200 il mese scorso
    from ai.strumenti import specialisti as strumenti_specialisti
    strumenti_specialisti.previsione(contesto, misura_aziendale="fatturazione.fatturato", per="mese", orizzonte=2)
    assert inviate[0][-1] == 0 and inviate[0][-2] == 200
    assert len(inviate[0]) == 8


def test_misura_non_installata(scena, contesto, monkeypatch):
    originale = modules.manifests_attivi
    monkeypatch.setattr(modules, "manifests_attivi",
                        lambda *a, **k: {s: m for s, m in originale(*a, **k).items() if s != "magazzino"})
    with pytest.raises(strumenti.ErroreStrumento, match="non è installata"):
        strumento_misure.misura(contesto, nome="magazzino.sotto_scorta")
    assert "magazzino.sotto_scorta" not in misure.testo_prompt()
    assert "fatturazione.fatturato" in misure.testo_prompt()


def _con_modello_finto():
    from ai.models import AnelloCatena, Modello, Profilo, Provider
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto")
    AnelloCatena.objects.create(profilo=Profilo.objects.create(nome="Chat", compito="chat"), modello=modello)


def test_provenienza_numeri_usati(scena, contesto, client):
    from ai import motore
    from ai.gateway import finto
    azienda, cliente, monitor, _ = scena
    _fattura(azienda, cliente, [(monitor, "5")], stato="emessa")
    _con_modello_finto()
    with finto.con_copione([[("strumento", "misura", {"nome": "fatturazione.fatturato", "periodo": "anno"}),
                             ("strumento", "misura", {"nome": "fatturazione.inesistente"})],
                            ["Il fatturato dell'anno è 1.000 €."]]):
        turno = motore.avvia(contesto.conversazione, "Fatturato?", contesto.utente, azienda)
    turno.refresh_from_db()
    numeri = turno.provenienza["numeri"]
    assert len(numeri) == 1
    n = numeri[0]
    assert (n["etichetta"], n["valore"], n["unita"]) == ("Fatturato", 1000, "€")
    assert n["periodo"] == "dell'anno in corso" and "note di credito" in n["definizione"]
    assert n["url"].startswith("/fatturazione/fatture/?")
    assert "note di credito" in n["nota_lista"]
    assert turno.provenienza["esito"] == "verificato"
    client.force_login(contesto.utente)
    pagina = client.get(f"/ai/chat/{contesto.conversazione.pk}/").content.decode()
    assert "1 numero usato" in pagina and "Apri i record" in pagina and "1.000 €" in pagina
