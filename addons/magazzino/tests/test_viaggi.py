"""Viaggi di consegna: tappe in ordine, partenza che spedisce le consegne aperte con il mezzo come vettore, esiti,
viaggio concluso, foglio di viaggio; colli con imballo sulla consegna."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from magazzino import viaggi
from magazzino.models import Collo, Consegna, ModelloImballo, RigaConsegna, TappaViaggio, Viaggio
from magazzino.tests.test_magazzino import scena  # noqa: F401


def test_viaggio(client, scena):  # noqa: F811
    azienda, magazzino, cliente, fornitore, monitor, _ = scena
    c1, c2 = (Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente) for _ in range(2))
    for c in (c1, c2):
        RigaConsegna.objects.create(consegna=c, prodotto=monitor, quantita=1)
    v = Viaggio.objects.create(azienda=azienda, magazzino=magazzino, mezzo="Furgone AB123CD")
    assert list(viaggi.consegne_da_caricare(v)) == [c1, c2]
    TappaViaggio.objects.create(viaggio=v, consegna=c2, ordine=1)
    TappaViaggio.objects.create(viaggio=v, consegna=c1, ordine=2)
    assert list(viaggi.consegne_da_caricare(v)) == []
    viaggi.parti(v)
    c1.refresh_from_db()
    assert v.stato == "in_corso" and c1.stato == "fatto" and c1.numero and "AB123CD" in c1.vettore
    with pytest.raises(ValidationError):
        viaggi.parti(v)
    t1, t2 = v.tappe.all()
    assert t1.consegna == c2
    viaggi.esito(t1, True)
    viaggi.esito(t2, False, "cliente assente")
    v.refresh_from_db()
    assert v.stato == "concluso"
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "cliente assente" in client.get(f"/magazzino/viaggi/{v.pk}/").content.decode()
    assert "Firma e ora" in client.get(f"/magazzino/viaggi/{v.pk}/foglio/").content.decode()


def test_colli(client, scena):  # noqa: F811
    azienda, magazzino, cliente, _, monitor, _ = scena
    scatola = ModelloImballo.objects.create(azienda=azienda, nome="Scatola media", lunghezza=60, larghezza=40, altezza=40, tara=Decimal("0.8"))
    c = Consegna.objects.create(azienda=azienda, magazzino=magazzino, cliente=cliente)
    Collo.objects.create(consegna=c, numero=1, imballo=scatola, peso=Decimal("12.5"), tracciamento="BRT123")
    assert str(scatola) == "Scatola media (60×40×40 cm)"
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "BRT123" in client.get(f"/magazzino/consegne/{c.pk}/").content.decode()
