"""Periodo sul grafico: Mese · Trimestre · Anno · Anno scorso e il confronto con l'anno prima, in chat e in Analisi."""
import datetime

import pytest
from django.contrib.auth.models import User

from ai import artifact, strumenti
from ai.models import Conversazione
from core import misure
from core.models import Azienda
from todo.models import Attivita

OGGI = datetime.date(2026, 11, 17)


@pytest.fixture
def contesto(db, monkeypatch):
    monkeypatch.setattr(misure, "_oggi", lambda: OGGI)
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    for scadenza in (datetime.date(2026, 3, 10), datetime.date(2026, 3, 20), datetime.date(2025, 3, 5), datetime.date(2026, 11, 2)):
        Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=str(scadenza), stato="aperta", scadenza=scadenza)
    return strumenti.Contesto(utente=capo, azienda=Azienda.objects.get(pk=1),
                              conversazione=Conversazione.objects.create(utente=capo, titolo="Periodo"))


def _spec(**altro):
    return {"tipo": "grafico", "vista": "todo.attivita", "per": "scadenza:mese", "misura": "count", "grafico": "barre",
            "filtri": {}, "testo": "", **altro}


def test_senza_periodo_tutti_i_mesi(contesto):
    assert sum(v for _, v in artifact.calcola(_spec(), contesto)["serie"]) == 4


def test_il_periodo_restringe_il_grafico(contesto):
    anno = artifact.calcola(_spec(periodo="anno"), contesto)
    assert sum(v for _, v in anno["serie"]) == 3 and "confronto" not in anno
    mese = artifact.calcola(_spec(periodo="mese"), contesto)
    assert [v for _, v in mese["serie"]] == [1]


def test_confronto_con_l_anno_prima_mese_per_mese(contesto):
    dati = artifact.calcola(_spec(periodo="anno", confronta=True), contesto)
    per_mese = dict(zip(dati["chiavi"], dati["confronto"]["valori"]))
    assert dati["confronto"]["etichetta"] == "Anno prima"
    assert per_mese["2026-03-01"] == 1 and per_mese["2026-11-01"] == 0     # marzo 2025 accanto a marzo 2026


def test_la_torta_non_ha_il_confronto(contesto):
    assert "confronto" not in artifact.calcola(_spec(periodo="anno", confronta=True, grafico="torta"), contesto)


def test_analisi_calcola_allo_stesso_modo(contesto):
    from core.viste.interroga import richiesta_di
    from grafici import motore
    from grafici.models import Grafico
    spec = {"vista": "todo.attivita", "per": "scadenza:mese", "misura": "count", "periodo": "anno", "confronta": True}
    req = richiesta_di(contesto.utente)
    dati = motore.dati_di(Grafico.BARRE, spec, req)
    assert sum(v for _, v in dati["serie"]) == 3
    serie = motore.serie_di(Grafico(tipo=Grafico.BARRE, titolo="x", spec=spec), dati, motore.vista_di(spec, req))
    assert serie["confronto"]["valori"] and serie["confronto"]["etichetta"] == "Anno prima"
