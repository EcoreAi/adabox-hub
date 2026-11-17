"""Misura aziendale del Magazzino: prodotti sotto scorta, la stessa della pagina giacenze e della dashboard."""
from decimal import Decimal

from core import misure
from core.viste.interroga import richiesta_di
from magazzino import dashboard
from magazzino.models import Movimento
from magazzino.pagine import situazione
from prodotti.models import Prodotto

from .test_magazzino import scena  # noqa: F401  (fixture)


def test_sotto_scorta_come_situazione(scena, superuser):
    azienda, magazzino, _, _, monitor, _ = scena
    tastiera = Prodotto.objects.create(azienda=azienda, nome="Tastiera", scorta_minima=Decimal("1"))
    Movimento.objects.create(azienda=azienda, magazzino=magazzino, prodotto=monitor, quantita=2)
    Movimento.objects.create(azienda=azienda, magazzino=magazzino, prodotto=tastiera, quantita=10)
    req = richiesta_di(superuser)
    r = misure.calcola("magazzino.sotto_scorta", req)
    assert r["valore"] == len(situazione(req, True)[1]) == 1
    assert r["gruppi"][0]["gruppo"] == "Monitor" and r["gruppi"][0]["valore"] == 3
    assert "sotto_scorta=1" in r["url"]
    assert dashboard.kpi(req)["kpi"][0]["valore"] == 1


def test_sotto_scorta_senza_permesso_rifiuta(scena):
    """Senza poter vedere i movimenti la giacenza sembrerebbe zero: la misura rifiuta invece di contare tutto."""
    import pytest
    from django.contrib.auth.models import Permission, User

    from core.viste.interroga import ErroreInterrogazione
    u = User.objects.create_user("mario", "m@example.com", "x")
    u.user_permissions.add(Permission.objects.get(codename="view_prodotto"))
    with pytest.raises(ErroreInterrogazione, match="permesso"):
        misure.calcola("magazzino.sotto_scorta", richiesta_di(User.objects.get(pk=u.pk)))
