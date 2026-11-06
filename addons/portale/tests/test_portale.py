"""Il portale clienti come modulo: sezioni dalle app, ogni cliente vede solo i suoi documenti, risposta ai preventivi
e PDF; gli accessi esistenti passano dall'assistenza al portale con permessi ed email personalizzate."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.urls import reverse

from contatti.models import Contatto
from core.models import Azienda
from fatturazione.models import Fattura, Scadenza
from portale.inviti import invita
from vendite.models import OrdineVendita


@pytest.fixture
def scena(db, settings, mailoutbox):
    azienda = Azienda.objects.get(pk=1)
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True)
    anna = Contatto.objects.create(azienda=azienda, nome="Anna Rossi", tipo="persona", societa=rossi, email="anna@rossi.it")
    bianchi = Contatto.objects.create(azienda=azienda, nome="Bianchi Spa", cliente=True, email="info@bianchi.it")
    interno = User.objects.create_superuser("sara", "sara@example.com", "x")
    return {"azienda": azienda, "rossi": rossi, "anna": anna, "bianchi": bianchi, "interno": interno}


def _entra(client, scena):
    accesso = invita(scena["anna"], scena["interno"])
    client.force_login(accesso.utente)
    return accesso


def _ordine(scena, cliente, stato, numero):
    return OrdineVendita.objects.create(azienda=scena["azienda"], cliente=cliente, stato=stato, numero=numero)


def _fattura(scena, cliente, stato, numero, residuo):
    f = Fattura.objects.create(azienda=scena["azienda"], cliente=cliente, numero=numero)
    Fattura.objects.filter(pk=f.pk).update(stato=stato, totale=Decimal("122.00"))
    if residuo:
        Scadenza.objects.create(fattura=f, data=datetime.date(2026, 12, 31), importo=Decimal(residuo))
    return f


def test_home_con_le_sezioni_delle_app(client, scena):
    _ordine(scena, scena["rossi"], OrdineVendita.INVIATO, "PRV/1")
    _fattura(scena, scena["rossi"], Fattura.EMESSA, "FT/1", "122.00")
    _entra(client, scena)
    html = client.get("/portale/").content.decode()
    for testo in ("Preventivi e ordini", "Fatture", "Richieste", "preventivi da guardare", "da pagare, in tutto 122,00 €"):
        assert testo in html, testo
    assert client.get("/dashboard/").url == "/portale/"                               # le app interne restano chiuse


def test_ognuno_vede_solo_i_suoi_documenti(client, scena):
    mio = _ordine(scena, scena["rossi"], OrdineVendita.INVIATO, "PRV/1")
    _ordine(scena, scena["rossi"], OrdineVendita.BOZZA, "PRV/BOZZA")
    altrui = _ordine(scena, scena["bianchi"], OrdineVendita.INVIATO, "PRV/ALTRUI")
    fattura = _fattura(scena, scena["rossi"], Fattura.EMESSA, "FT/1", "50.00")
    _fattura(scena, scena["rossi"], Fattura.BOZZA, "FT/BOZZA", 0)
    altra = _fattura(scena, scena["bianchi"], Fattura.EMESSA, "FT/ALTRUI", "10.00")
    _entra(client, scena)
    ordini = client.get(reverse("vendite:portale_ordini")).content.decode()
    assert "PRV/1" in ordini and "PRV/BOZZA" not in ordini and "PRV/ALTRUI" not in ordini and "/vendite/preventivo/" in ordini
    fatture = client.get(reverse("fatturazione:portale_fatture")).content.decode()
    assert "FT/1" in fatture and "50,00 €" in fatture and "FT/BOZZA" not in fatture and "FT/ALTRUI" not in fatture
    assert client.get(reverse("vendite:portale_pdf", args=[altrui.pk])).status_code == 404
    assert client.get(reverse("fatturazione:portale_pdf", args=[altra.pk])).status_code == 404
    pdf = client.get(reverse("fatturazione:portale_pdf", args=[fattura.pk]))
    assert pdf.status_code in (200, 503)                                              # 503 senza Pango (fuori da Docker)
    assert client.get(reverse("vendite:portale_pdf", args=[mio.pk])).status_code in (200, 503)


def test_risposta_al_preventivo_dal_portale(client, scena):
    import re
    ordine = _ordine(scena, scena["rossi"], OrdineVendita.INVIATO, "PRV/1")
    _entra(client, scena)
    link = re.search(r'href="(/vendite/preventivo/[^"]+)"', client.get(reverse("vendite:portale_ordini")).content.decode()).group(1)
    assert client.get(link).status_code == 200                                        # il cliente ci arriva dal portale
    client.post(link, {"azione": "accetta", "nome": "Anna Rossi", "conferma": "1"})
    ordine.refresh_from_db()
    assert ordine.risposta == OrdineVendita.ACCETTATO


def test_invito_e_sospensione_con_i_permessi_del_portale(client, scena):
    from portale.models import AccessoPortale
    commerciale = User.objects.create_user("luca", password="x")
    commerciale.user_permissions.set(Permission.objects.filter(content_type__app_label="contatti"))
    client.force_login(commerciale)
    assert client.post(f"/portale/contatto/{scena['anna'].pk}/invita/").status_code == 403
    commerciale.user_permissions.add(Permission.objects.get(content_type__app_label="portale", codename="add_accessoportale"))
    client.force_login(User.objects.get(pk=commerciale.pk))
    client.post(f"/portale/contatto/{scena['anna'].pk}/invita/")
    accesso = AccessoPortale.objects.get(contatto=scena["anna"])
    assert accesso.utente.profilo.esterno
