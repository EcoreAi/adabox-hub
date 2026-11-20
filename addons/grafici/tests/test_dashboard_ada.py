"""Dashboard fatte da Ada: una frase, una conferma, una pagina di Analisi con indicatori e grafici veri."""
import pytest
from django.contrib.auth.models import User

from ai import strumenti
from ai.strumenti import ErroreStrumento
from fatturazione.tests.test_fatturazione import _fattura, scena  # noqa: F401  (fixture)
from grafici import ai as strumenti_analisi
from grafici.models import Grafico, Pagina

KPI_FATTURATO = {"tipo": "kpi", "misura_aziendale": "fatturazione.fatturato", "periodo": "mese"}
KPI_SCADUTO = {"tipo": "kpi", "misura_aziendale": "fatturazione.scaduto"}
PER_CLIENTE = {"tipo": "torta", "misura_aziendale": "fatturazione.fatturato", "per": "cliente", "titolo": "Fatturato per cliente"}
PER_MESE = {"tipo": "barre", "misura_aziendale": "fatturazione.fatturato", "per": "mese", "periodo": "trimestre"}
SCADUTO_PER_CLIENTE = {"tipo": "barre", "misura_aziendale": "fatturazione.scaduto", "per": "cliente",
                       "titolo": "Scaduto per cliente"}


@pytest.fixture
def contesto(scena):
    azienda, cliente, monitor, _ = scena
    _fattura(azienda, cliente, [(monitor, "5")], stato="emessa")
    return strumenti.Contesto(utente=User.objects.create_superuser("capo", "capo@example.com", "x"), azienda=azienda)


def test_dashboard_con_un_colpo(contesto):
    pezzi = [PER_CLIENTE, KPI_FATTURATO, PER_MESE, KPI_SCADUTO]
    anteprima = strumenti_analisi.anteprima_crea_dashboard(contesto, "Vendite", pezzi)
    assert "Vendite" in anteprima["titolo"] and len([d for d in anteprima["dettagli"] if d["campo"] not in ("Tolti", "Dove")]) == 4
    r = strumenti_analisi.crea_dashboard(contesto, "Vendite", pezzi)
    p = Pagina.objects.get(pk=r["pagina"])
    assert p.titolo == "Vendite" and p.utente == contesto.utente and r["url"]
    grafici = {g.pk: g for g in Grafico.objects.filter(pk__in=r["grafici"])}
    assert len(grafici) == 4 and all(g.origine == Grafico.CHAT and g.dati for g in grafici.values())
    voci = p.layout["widget"]
    tipi = [grafici[int(v["id"][2:])].tipo for v in voci]
    assert tipi == ["kpi", "kpi", "torta", "barre"]                       # prima gli indicatori, poi l'ordine di Ada
    assert [v["w"] for v in voci] == [1, 1, 2, 2]
    torta = next(g for g in grafici.values() if g.tipo == "torta")
    assert torta.spec["periodo"] == "anno" and torta.titolo == "Fatturato per cliente"
    assert next(g for g in grafici.values() if g.tipo == "barre").spec["periodo"] == "trimestre"


def test_grafico_vuoto_tolto_kpi_a_zero_resta(contesto):
    pezzi = [KPI_SCADUTO, SCADUTO_PER_CLIENTE, PER_CLIENTE]
    anteprima = strumenti_analisi.anteprima_crea_dashboard(contesto, "Incassi", pezzi)
    tolti = [d["dopo"] for d in anteprima["dettagli"] if d["campo"] == "Tolti"]
    assert len(tolti) == 1 and "Scaduto per cliente" in tolti[0] and "nessun dato" in tolti[0]
    r = strumenti_analisi.crea_dashboard(contesto, "Incassi", pezzi)
    assert sorted(Grafico.objects.filter(pk__in=r["grafici"]).values_list("tipo", flat=True)) == ["kpi", "torta"]
    assert "Scaduto per cliente" in r["esito"]                             # Ada sa dire che cosa ha tolto


def test_pezzo_sbagliato_tolto_con_il_motivo(contesto):
    pezzi = [KPI_FATTURATO, PER_CLIENTE, {"tipo": "barre", "misura_aziendale": "nessuna.misura", "per": "cliente"}]
    anteprima = strumenti_analisi.anteprima_crea_dashboard(contesto, "Prova", pezzi)
    assert any(d["campo"] == "Tolti" and "nessuna.misura" in d["dopo"] for d in anteprima["dettagli"])
    assert len(strumenti_analisi.crea_dashboard(contesto, "Prova", pezzi)["grafici"]) == 2


def test_meno_di_due_pezzi_niente_dashboard(contesto):
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "Vuota", [KPI_FATTURATO, SCADUTO_PER_CLIENTE])
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.crea_dashboard(contesto, "Vuota", [KPI_FATTURATO, SCADUTO_PER_CLIENTE])
    assert not Pagina.objects.filter(titolo="Vuota").exists() and not Grafico.objects.exists()


def test_titolo_gia_usato(contesto):
    Pagina.objects.create(utente=contesto.utente, titolo="Vendite")
    with pytest.raises(ErroreStrumento, match="esiste già"):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "vendite", [KPI_FATTURATO, PER_CLIENTE])


def test_piu_di_otto_pezzi(contesto):
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "Troppi", [KPI_FATTURATO] * 9)


def test_pezzi_non_lista(contesto):
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "Testo", '[{"tipo": "kpi"}]')
    with pytest.raises(ErroreStrumento):
        strumenti_analisi.anteprima_crea_dashboard(contesto, "Testo", [KPI_FATTURATO, "fatturato"])
