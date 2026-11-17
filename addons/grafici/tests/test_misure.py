"""Un grafico o un KPI di Analisi su una misura aziendale si ricalcola con la definizione della misura."""
from django.contrib.auth.models import User

from core.viste.interroga import richiesta_di
from fatturazione.tests.test_fatturazione import _fattura, scena  # noqa: F401  (fixture)
from grafici import motore
from grafici.models import Grafico


def test_grafico_salvato_con_misura(scena):
    azienda, cliente, monitor, _ = scena
    _fattura(azienda, cliente, [(monitor, "5")], stato="emessa")
    _fattura(azienda, cliente, [(monitor, "2")], stato="emessa", tipo="TD04")
    req = richiesta_di(User.objects.create_superuser("capo", "capo@example.com", "x"))
    spec = {"misura_aziendale": "fatturazione.fatturato", "per": "cliente", "periodo": "anno"}
    dati = motore.dati_di(Grafico.TORTA, spec, req)
    assert dati["totale"] == 600 and dati["serie"] == [("Rossi Srl", 600)]
    assert motore.vista_di(spec, req) is not None
    assert "Fatturato" in motore.descrizione(spec, request=req)
    kpi = motore.dati_di(Grafico.KPI, {"misura_aziendale": "fatturazione.fatturato", "periodo": "mese"}, req)
    assert kpi["valore"] == 600 and len(kpi["storico"]) == 12


def test_ada_salva_kpi_su_misura(scena):
    from ai import strumenti
    from grafici import ai as strumenti_analisi
    azienda, cliente, monitor, _ = scena
    _fattura(azienda, cliente, [(monitor, "1")], stato="emessa")
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    contesto = strumenti.Contesto(utente=capo, azienda=azienda)
    r = strumenti_analisi.salva_grafico(contesto, tipo="kpi", misura_aziendale="fatturazione.fatturato", periodo="mese")
    g = Grafico.objects.get(pk=r["grafico"])
    assert g.spec == {"misura_aziendale": "fatturazione.fatturato", "periodo": "mese"}
    assert g.dati["valore"] == 200 and g.titolo.startswith("Fatturato")
