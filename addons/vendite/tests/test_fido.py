"""Il fido del cliente: esposizione, avviso e blocco alla conferma, anche online."""
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command

import fiscale
from contatti.models import Contatto
from core.models import Azienda, Messaggio
from fatturazione import operazioni as fatture
from fatturazione.models import DatiFiscali, Fattura
from fiscale.models import AliquotaIva
from vendite import fido, operazioni
from vendite.models import OrdineVendita, RigaVendita


@pytest.fixture
def s(db, client):
    call_command("loaddata", str(Path(fiscale.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva, azienda.indirizzo, azienda.cap, azienda.citta, azienda.provincia = (
        "01234567897", "Via Roma 1", "00100", "Roma", "RM")
    azienda.save()
    DatiFiscali.objects.create(azienda=azienda, iban="IT60X0542811101000000123456", banca="Banca")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, email="rossi@example.com",
                                      partita_iva="12345678903", codice_sdi="ABC1234", indirizzo="Via Po 2", cap="20100",
                                      citta="Milano", provincia="MI")
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    client.force_login(root)
    return {"azienda": azienda, "cliente": cliente}


def _ordine(s, prezzo="1000", numero="PV/1", stato=OrdineVendita.BOZZA, **extra):
    o = OrdineVendita.objects.create(azienda=s["azienda"], cliente=s["cliente"], numero=numero, stato=stato, **extra)
    RigaVendita.objects.create(ordine=o, descrizione="Lavoro", prezzo=D(prezzo), aliquota=AliquotaIva.objects.get(codice="22"))
    o.ricalcola()
    return o


def _fido(s, valore, blocca=False):
    Contatto.objects.filter(pk=s["cliente"].pk).update(fido=valore, fido_blocca=blocca)
    s["cliente"].refresh_from_db()


def _conferma(client, o):
    return client.post(f"/vendite/ordini/{o.pk}/bottone/conferma/", follow=True)


def test_senza_fido_nessun_controllo(s):
    o = _ordine(s)
    assert fido.situazione(s["cliente"]) is None and fido.controllo(o) is None


def test_fido_zero_e_un_fido(s):
    _fido(s, 0, True)
    assert fido.controllo(_ordine(s))["blocca"]


def test_esposizione_conta_ordini_e_scadenze_una_volta_sola(s):
    confermato = _ordine(s, stato=OrdineVendita.CONFERMATO, numero="PV/2", numero_ordine="OV/1")
    assert fido.esposizione(s["cliente"]) == {"scadenze": D(0), "ordini": D("1220.00"), "totale": D("1220.00")}
    fattura = fatture.da_ordine(confermato)
    assert fido.esposizione(s["cliente"])["ordini"] == D("1220.00")       # in bozza non ha ancora scadenze
    fatture.emetti(fattura)
    assert fido.esposizione(s["cliente"]) == {"scadenze": D("1220.00"), "ordini": D(0), "totale": D("1220.00")}
    fatture.incassa_fattura(Fattura.objects.get(pk=fattura.pk), D("220"))
    assert fido.esposizione(s["cliente"])["totale"] == D("1000.00")


def test_esattamente_al_fido_si_conferma(s):
    _fido(s, D("1220"), True)
    assert fido.controllo(_ordine(s)) is None


def test_oltre_il_fido_avvisa_ma_conferma_e_lascia_traccia(client, s):
    _fido(s, D("500"))
    o = _ordine(s)
    assert "Fido di Rossi Srl superato" in _conferma(client, o).content.decode()
    o.refresh_from_db()
    assert o.stato == OrdineVendita.CONFERMATO
    assert Messaggio.objects.filter(object_id=o.pk, corpo__contains="oltre il fido").exists()


def test_con_il_blocco_non_conferma(client, s):
    _fido(s, D("500"), True)
    o = _ordine(s)
    assert "Ordine non confermato" in _conferma(client, o).content.decode()
    o.refresh_from_db()
    assert o.stato == OrdineVendita.BOZZA and not o.numero_ordine
    _fido(s, D("5000"), True)
    _conferma(client, o)
    o.refresh_from_db()
    assert o.stato == OrdineVendita.CONFERMATO


def test_online_con_il_blocco_l_accettazione_resta_ma_l_ordine_aspetta(s):
    _fido(s, D("500"), True)
    capo = User.objects.create_user("capo", "capo@example.com", "x")
    o = _ordine(s, stato=OrdineVendita.INVIATO, commerciale=capo)
    mail.outbox.clear()
    o = operazioni.accetta(o, "Mario Rossi")
    o.refresh_from_db()
    assert o.risposta == OrdineVendita.ACCETTATO and o.stato == OrdineVendita.INVIATO and not o.numero_ordine
    assert [m.to for m in mail.outbox] == [["capo@example.com"]]           # al cliente non si parla del fido
    assert "non è confermato" in mail.outbox[0].body


def test_online_senza_blocco_conferma_e_annota(s):
    _fido(s, D("500"))
    o = operazioni.accetta(_ordine(s, stato=OrdineVendita.INVIATO), "Mario Rossi")
    o.refresh_from_db()
    assert o.stato == OrdineVendita.CONFERMATO
    assert Messaggio.objects.filter(object_id=o.pk, corpo__contains="oltre il fido").exists()


def test_sezioni_nei_dettagli(client, s):
    _fido(s, D("500"), True)
    o = _ordine(s)
    assert "Conferma bloccata" in client.get(f"/vendite/ordini/{o.pk}/").content.decode()
    pagina = client.get(f"/contatti/contatti/{s['cliente'].pk}/").content.decode()
    assert "Fido concesso" in pagina and "non si possono confermare" in pagina
