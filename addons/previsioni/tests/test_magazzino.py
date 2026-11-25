"""Magazzino: consumo, soglie, partenza e proiezione fino alle date di esaurimento e riordino."""
import datetime
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from previsioni import magazzino as pm

serve_magazzino = pytest.mark.skipif(not apps.is_installed("magazzino"), reason="serve Magazzino")   # la proiezione no

if apps.is_installed("magazzino"):
    from magazzino.models import Consegna, Inventario, Magazzino, Movimento, Ricevimento, RigaConsegna, ScortaMagazzino
    from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)

OGGI = date(2026, 11, 25)
ORIZZONTE = [(25, 30, 35)] * 12
NOV = date(2026, 11, 1)


def proietta(partenza=120, futuro=ORIZZONTE, per="mese", primo=NOV, sotto=60, riporta=150, oggi=OGGI):
    return pm.proietta(partenza, futuro, per, primo, sotto, riporta, oggi)


def test_esaurimento_e_riordino_dalla_mediana():
    r = proietta()
    assert r["riordino"] == date(2027, 1, 25)
    assert r["esaurimento"] == date(2027, 3, 25)
    assert r["esaurimento_da"] == date(2027, 3, 8)
    assert r["esaurimento_a"] == date(2027, 4, 18)
    assert r["quantita_suggerita"] == Decimal("90.194")
    assert r["stato"] == "ok"


def test_quantita_suggerita_tre_mesi_senza_riporta_a():
    assert proietta(riporta=None)["quantita_suggerita"] == 90


def test_quantita_suggerita_fino_a_riporta_a():
    r = proietta()
    assert r["quantita_suggerita"] == Decimal("90.194")


def test_gia_sotto_soglia_riordina_ora():
    r = proietta(partenza=40)
    assert r["stato"] == "riordina_ora" and r["riordino"] == OGGI
    assert r["esaurimento"] is not None            # le date di esaurimento si calcolano comunque


def test_giacenza_zero_finito():
    r = proietta(partenza=0)
    assert r["stato"] == "finito"


def test_nessun_consumo():
    r = proietta(futuro=[(0, 0, 0)] * 12)
    assert r["stato"] == "nessun_consumo"
    assert (r["esaurimento"], r["esaurimento_da"], r["esaurimento_a"], r["riordino"], r["quantita_suggerita"]) == (None,) * 5


def test_riordina_ora_vince_su_nessun_consumo():
    r = proietta(partenza=40, futuro=[(0, 0, 0)] * 12)
    assert r["stato"] == "riordina_ora" and r["riordino"] == OGGI
    assert r["quantita_suggerita"] == 110
    assert (r["esaurimento"], r["esaurimento_da"], r["esaurimento_a"]) == (None,) * 3


def test_oltre_l_orizzonte():
    r = proietta(futuro=[(0, 1, 2)] * 12)
    assert r["stato"] == "oltre"
    assert r["riordino"] is None and r["esaurimento"] is None


def test_senza_soglia_solo_esaurimento():
    for soglia in (None, 0):
        r = proietta(sotto=soglia)
        assert r["riordino"] is None and r["quantita_suggerita"] is None
        assert r["esaurimento"] == date(2027, 3, 25) and r["stato"] == "ok"


def test_settimane():
    # lunedì 2026-11-23, 7 mediane di 14 a settimana = 2 al giorno
    r = pm.proietta(10, [(1, 14, 28)] * 8, "settimana", date(2026, 11, 23), 4, None, OGGI)
    assert r["esaurimento"] == date(2026, 11, 29)       # 25..29 = 5 giorni x 2 = 10
    assert r["riordino"] == date(2026, 11, 28)          # fine giornata: 8, 6, 4 (non < 4), 2
    assert r["quantita_suggerita"] == 98                # le 7 settimane che restano, 14 l'una


# ---- database --------------------------------------------------------------------------------------------------

def _mov(s, tipo, q, giorno, magazzino=None, causale="", doc=None, prodotto=None):
    ct = ContentType.objects.get_for_model(doc) if doc is not None else None
    return Movimento.objects.create(
        azienda=s["azienda"], prodotto=prodotto or s["monitor"], magazzino=magazzino or s["magazzino"], quantita=q, tipo=tipo,
        causale=causale, data=timezone.make_aware(datetime.datetime.combine(giorno, datetime.time(10))),
        content_type=ct, object_id=doc.pk if doc is not None else None)


@pytest.fixture
def s(scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, _ = scena
    negozio = Magazzino.objects.create(azienda=azienda, nome="Negozio")
    return {"azienda": azienda, "magazzino": magazzino, "negozio": negozio, "monitor": monitor, "cliente": cliente,
            "fornitore": fornitore}


def _consegna(s):
    return Consegna.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], cliente=s["cliente"])


@serve_magazzino
def test_consumi_contano_prelievi_a_mano_non_inventari(s):
    inv = Inventario.objects.create(azienda=s["azienda"], magazzino=s["magazzino"])
    _mov(s, Movimento.RETTIFICA, 100, date(2026, 1, 1), causale="Inventario iniziale")
    _mov(s, Movimento.SCARICO, -3, date(2026, 10, 5))
    _mov(s, Movimento.RETTIFICA, -2, date(2026, 10, 6))                       # prelievo a mano
    _mov(s, Movimento.RETTIFICA, -7, date(2026, 10, 7), causale="Inv.", doc=inv)   # inventario
    _mov(s, Movimento.RETTIFICA, -9, date(2026, 10, 8), causale="Inventario iniziale")
    _mov(s, Movimento.RETTIFICA, 4, date(2026, 10, 9))                         # positiva
    c = pm.consumi(s["azienda"], "mese")
    chiave = (s["monitor"].pk, s["magazzino"].pk)
    assert c[chiave] == {date(2026, 10, 1): 5}
    assert c[(s["monitor"].pk, None)] == {date(2026, 10, 1): 5}


@serve_magazzino
def test_storno_di_consegna_si_compensa(s):
    cons = _consegna(s)
    _mov(s, Movimento.SCARICO, -10, date(2026, 10, 5), doc=cons)
    _mov(s, Movimento.CARICO, 4, date(2026, 11, 2), doc=cons)                  # storno parziale a novembre
    c = pm.consumi(s["azienda"], "mese")[(s["monitor"].pk, None)]
    assert c == {date(2026, 10, 1): 6}


@serve_magazzino
def test_storno_di_ricevimento_non_e_consumo(s):
    r = Ricevimento.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], fornitore=s["fornitore"])
    _mov(s, Movimento.CARICO, 10, date(2026, 10, 1), doc=r)
    _mov(s, Movimento.SCARICO, -4, date(2026, 10, 5), doc=r)                   # storno del ricevimento
    assert pm.consumi(s["azienda"], "mese") == {}


@serve_magazzino
def test_valori_mai_sotto_zero(s):
    cons = _consegna(s)
    _mov(s, Movimento.SCARICO, -2, date(2026, 10, 5), doc=cons)
    _mov(s, Movimento.CARICO, 5, date(2026, 10, 6), doc=cons)
    assert pm.consumi(s["azienda"], "mese")[(s["monitor"].pk, None)] == {date(2026, 10, 1): 0}


@serve_magazzino
def test_trasferimenti_solo_per_magazzino(s):
    _mov(s, Movimento.TRASFERIMENTO, -6, date(2026, 10, 5), magazzino=s["magazzino"])
    _mov(s, Movimento.TRASFERIMENTO, 6, date(2026, 10, 5), magazzino=s["negozio"])
    c = pm.consumi(s["azienda"], "mese")
    assert c[(s["monitor"].pk, s["magazzino"].pk)] == {date(2026, 10, 1): 6}
    assert (s["monitor"].pk, s["negozio"].pk) not in c
    assert (s["monitor"].pk, None) not in c


@serve_magazzino
def test_trasferimento_fra_ubicazioni_dello_stesso_magazzino_non_e_consumo(s):
    from magazzino import operazioni
    from magazzino.models import Ubicazione
    a = Ubicazione.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], codice="A")
    b = Ubicazione.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], codice="B")
    Movimento.objects.create(azienda=s["azienda"], prodotto=s["monitor"], magazzino=s["magazzino"], ubicazione=a, quantita=20,
                             tipo=Movimento.CARICO)
    operazioni.trasferisci(s["monitor"], 3, s["magazzino"], s["magazzino"], da_ubicazione=a, a_ubicazione=b)
    c = pm.consumi(s["azienda"], "mese")
    assert (s["monitor"].pk, s["magazzino"].pk) not in c
    operazioni.trasferisci(s["monitor"], 2, s["magazzino"], s["negozio"])
    assert pm.consumi(s["azienda"], "mese")[(s["monitor"].pk, s["magazzino"].pk)] == {timezone.localdate().replace(day=1): 2}


@serve_magazzino
def test_consumi_settimanali(s):
    _mov(s, Movimento.SCARICO, -3, date(2026, 11, 25))     # mercoledì
    assert pm.consumi(s["azienda"], "settimana")[(s["monitor"].pk, None)] == {date(2026, 11, 23): 3}


@serve_magazzino
def test_soglie_magazzino_poi_acquisti_poi_scorta_minima(s):
    from acquisti.models import RegolaRiordino
    from prodotti.models import Prodotto
    a = s["azienda"]
    altro = Prodotto.objects.create(azienda=a, nome="Cavo", scorta_minima=8)
    terzo = Prodotto.objects.create(azienda=a, nome="Vite", scorta_minima=0)
    for p in (s["monitor"], altro, terzo):
        _mov(s, Movimento.CARICO, 10, date(2026, 10, 1), prodotto=p)
    ScortaMagazzino.objects.create(azienda=a, magazzino=s["negozio"], prodotto=s["monitor"], punto_riordino=3, scorta_obiettivo=9)
    RegolaRiordino.objects.create(azienda=a, prodotto=altro, punto_riordino=20, scorta_obiettivo=40)
    k = pm.chiavi_e_soglie(a)
    assert k[(s["monitor"].pk, s["negozio"].pk)] == (3, 9)
    assert (s["monitor"].pk, None) not in k
    assert k[(altro.pk, None)] == (20, 40)                    # la regola vince sulla scorta minima
    assert k[(terzo.pk, None)] == (None, None)


@serve_magazzino
def test_scorta_minima_senza_acquisti(s, monkeypatch):
    monkeypatch.setattr(pm.apps, "is_installed", lambda nome: False)
    _mov(s, Movimento.CARICO, 10, date(2026, 10, 1))
    assert pm.chiavi_e_soglie(s["azienda"])[(s["monitor"].pk, None)] == (5, None)


@serve_magazzino
def test_partenze(s):
    cons = _consegna(s)
    RigaConsegna.objects.create(consegna=cons, prodotto=s["monitor"], quantita=4)
    _mov(s, Movimento.CARICO, 20, date(2026, 10, 1))
    _mov(s, Movimento.CARICO, 5, date(2026, 10, 1), magazzino=s["negozio"])
    p = pm.partenze(s["azienda"])
    assert p[(s["monitor"].pk, s["magazzino"].pk)] == 16
    assert p[(s["monitor"].pk, s["negozio"].pk)] == 5
    assert p[(s["monitor"].pk, None)] == 21


@serve_magazzino
def test_settimane_con_meno_di_un_anno(s):
    assert pm.per_della_storia(s["azienda"]) == "settimana"          # nessun movimento
    oggi = timezone.localdate()
    _mov(s, Movimento.CARICO, 1, oggi - datetime.timedelta(days=200))
    assert pm.per_della_storia(s["azienda"]) == "settimana"
    _mov(s, Movimento.CARICO, 1, oggi.replace(year=oggi.year - 1) - datetime.timedelta(days=1))
    assert pm.per_della_storia(s["azienda"]) == "mese"
