"""Report di magazzino: giacenza a una data passata, CSV delle giacenze, anzianità per fasce con CSV."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from magazzino.models import Movimento
from magazzino.pagine import anzianita_di
from magazzino.tests.test_magazzino import scena  # noqa: F401  (fixture)

OGGI = timezone.localdate()


def _mov(s, quantita, giorni_fa, tipo="carico", costo=None):
    azienda, magazzino, _, _, monitor, _ = s
    return Movimento.objects.create(azienda=azienda, prodotto=monitor, magazzino=magazzino, quantita=quantita, tipo=tipo,
                                    costo_unitario=costo, data=timezone.now() - datetime.timedelta(days=giorni_fa))


@pytest.fixture
def s(scena, client):  # noqa: F811
    _mov(scena, 10, 400, costo=Decimal("50"))
    _mov(scena, 5, 100, costo=Decimal("50"))
    _mov(scena, 4, 10, costo=Decimal("50"))
    _mov(scena, -12, 5, tipo="scarico")
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    return scena


def test_giacenza_a_data_e_csv(client, s):
    passato = (OGGI - datetime.timedelta(days=50)).isoformat()
    html = client.get(f"/magazzino/giacenze/?data={passato}").content.decode()
    assert "Giacenze al" in html
    assert "Previsto" not in html
    csv = client.get(f"/magazzino/giacenze/?data={passato}&formato=csv").content.decode("utf-8-sig")
    assert "Monitor" in csv and "15,000" in csv and "Previsto" not in csv
    oggi = client.get("/magazzino/giacenze/?formato=csv").content.decode("utf-8-sig")
    assert "Previsto" in oggi and "7,000" in oggi


def test_anzianita(client, s):
    azienda, _, _, _, monitor, _ = s
    r, = anzianita_di([monitor], OGGI)
    assert r["quantita"] == 7 and r["fasce"] == [4, 0, 3, 0, 0]          # 4 dagli ultimi 10 giorni, 3 da 100 giorni fa
    html = client.get("/magazzino/anzianita/").content.decode()
    assert "Anzianità del magazzino" in html and "Monitor" in html
    assert "Carico più vecchio" in client.get("/magazzino/anzianita/?formato=csv").content.decode("utf-8-sig")
