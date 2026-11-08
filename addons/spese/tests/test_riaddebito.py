"""FIN-24: spese riaddebitate al cliente con una fattura in bozza, ricevuta dalla fotocamera, rimborso abbinato al
movimento bancario che lo paga."""
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import Permission

from contatti.models import Contatto
from spese import flusso, riaddebito
from spese.models import NotaSpese, RigaSpesa
from spese.tests.test_spese import OGGI, _form, scena  # noqa: F401  (fixture)


def _approvata(s, cliente=None):
    s["vitto"].ricevuta_obbligatoria = False
    s["vitto"].save()
    nota = NotaSpese.objects.create(azienda=s["azienda"], dipendente=s["mario"], titolo="Cliente Rossi")
    RigaSpesa.objects.create(nota=nota, data=OGGI, categoria=s["vitto"], descrizione="Pranzo", importo=Decimal("40"), cliente=cliente)
    RigaSpesa.objects.create(nota=nota, data=OGGI, categoria=s["vitto"], descrizione="Cena interna", importo=Decimal("30"))
    flusso.invia(nota, s["mario_u"])
    flusso.decidi(nota, s["capo_u"], True)
    return NotaSpese.objects.get(pk=nota.pk)


def test_la_ricevuta_propone_la_fotocamera_e_il_cliente(client, scena):
    client.force_login(scena["mario_u"])
    html = client.get("/spese/note/nuovo/").content.decode()
    assert 'accept="image/*,application/pdf"' in html and 'name="righe0-0-cliente"' in html


@pytest.mark.skipif(not apps.is_installed("fatturazione"), reason="serve Fatturazione")
def test_riaddebito_in_fattura_e_ritorno_se_annullata(client, scena):
    from fatturazione.models import Fattura
    rossi = Contatto.objects.create(nome="Rossi Srl", **({"azienda": scena["azienda"]} if any(f.name == "azienda" for f in Contatto._meta.fields) else {}))
    nota = _approvata(scena, rossi)
    (riga,) = riaddebito.da_riaddebitare(scena["azienda"])
    assert riga.descrizione == "Pranzo"                                  # solo quella con il cliente
    scena["hr_u"].user_permissions.add(*Permission.objects.filter(content_type__app_label="fatturazione"))
    client.force_login(scena["hr_u"])
    pagina = client.get("/spese/riaddebiti/").content.decode()
    assert "Rossi Srl" in pagina and "Pranzo" in pagina and "Cena interna" not in pagina
    r = client.post("/spese/riaddebiti/", {"cliente": rossi.pk, "riga": [riga.pk]})
    f = Fattura.objects.get(cliente=rossi)
    assert r.url.endswith(f"/{f.pk}/") and f.stato == Fattura.BOZZA
    assert [(x.descrizione.startswith("Spesa del"), x.prezzo) for x in f.righe.all()] == [(True, Decimal("40.00"))]
    assert RigaSpesa.objects.get(pk=riga.pk).riaddebitata_in == f.pk and not riaddebito.da_riaddebitare(scena["azienda"])
    f.delete()                                                           # la fattura non c'è più: torna da riaddebitare
    assert RigaSpesa.objects.get(pk=riga.pk).riaddebitata_in is None


@pytest.mark.skipif(not apps.is_installed("banca"), reason="serve Banca")
def test_rimborso_abbinato_al_movimento(client, scena):
    from banca import abbina
    from banca.models import Conto, MovimentoBanca
    nota = _approvata(scena)
    conto = Conto.objects.create(azienda=scena["azienda"], nome="Principale", iban="IT60X0542811101000000123456")
    giusto = MovimentoBanca.objects.create(azienda=scena["azienda"], conto=conto, data=OGGI, importo=-nota.totale,
                                           descrizione="Bonifico rimborso Rossi", impronta="a")
    MovimentoBanca.objects.create(azienda=scena["azienda"], conto=conto, data=OGGI, importo=Decimal("-5"), impronta="b")  # troppo piccolo
    scena["hr_u"].user_permissions.add(Permission.objects.get(codename="view_movimentobanca"))
    client.force_login(scena["hr_u"])
    pagina = client.get(f"/spese/rimborso/{nota.pk}/").content.decode()
    assert "Bonifico rimborso Rossi" in pagina and "-5,00" not in pagina and "-5.00" not in pagina and "checked" in pagina
    client.post(f"/spese/rimborso/{nota.pk}/", {"movimento": giusto.pk, "data": ""})
    nota.refresh_from_db()
    giusto.refresh_from_db()
    assert nota.stato == NotaSpese.RIMBORSATA and nota.rimborsata_il == OGGI and giusto.stato == MovimentoBanca.ABBINATO
    assert riaddebito.pagamento_di(nota) == giusto
    assert "Rimborso pagato con il movimento" in client.get(f"/spese/note/{nota.pk}/").content.decode()
    abbina.annulla(abbina.abbinamenti_di(nota).get())                    # dalla banca si toglie l'abbinamento
    giusto.refresh_from_db()
    assert giusto.stato == MovimentoBanca.DA_ABBINARE
