"""Posizioni fiscali e dichiarazioni d'intento: aliquote automatiche per clienti UE con partita IVA ed extra UE (beni e
servizi), posizione scelta per il cliente, N3.5 con la dichiarazione e il plafond all'emissione, protocollo nell'XML,
listino IVA inclusa scorporato, sezione sulla scheda del contatto."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from fatturazione import hooks, operazioni, posizioni
from fatturazione.models import DatiFiscali, DichiarazioneIntento, Fattura, PosizioneContatto, PosizioneFiscale, RigaFattura
from fiscale.models import AliquotaIva
from prodotti.models import Listino, PrezzoListino, Prodotto

OGGI = datetime.date.today()


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    hooks.posizioni_predefinite()
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva, azienda.indirizzo, azienda.cap, azienda.citta, azienda.provincia = "01234567897", "Via Roma 1", "00100", "Roma", "RM"
    azienda.save()
    DatiFiscali.objects.get_or_create(azienda=azienda, defaults={"iban": "IT60X0542811101000000123456"})
    bene = Prodotto.objects.create(azienda=azienda, nome="Macchina", prezzo_vendita=Decimal("1000"))
    servizio = Prodotto.objects.create(azienda=azienda, nome="Consulenza", tipo="servizio", prezzo_vendita=Decimal("100"))
    return {"azienda": azienda, "bene": bene, "servizio": servizio}


def _cliente(s, nome, nazione="IT", piva=""):
    return Contatto.objects.create(azienda=s["azienda"], nome=nome, cliente=True, nazione=nazione, partita_iva=piva,
                                   codice_fiscale="" if piva else "RSSMRA80A01H501U", indirizzo="Via 1", cap="00100", citta="Roma")


def test_automatiche(s):
    tedesco, svizzero, privato_fr = _cliente(s, "GmbH", "DE", "DE123456789"), _cliente(s, "AG", "CH", "CHE123"), _cliente(s, "Jean", "FR")
    a22 = AliquotaIva.objects.get(codice="22")
    assert posizioni.aliquota_per(tedesco, s["bene"], a22).natura == "N3.2"
    assert posizioni.aliquota_per(tedesco, s["servizio"], a22).natura == "N2.1"
    assert posizioni.aliquota_per(svizzero, s["bene"], a22).natura == "N3.1"
    assert posizioni.aliquota_per(privato_fr, s["bene"], a22) == a22                  # privato UE: IVA italiana
    n4 = AliquotaIva.objects.get(codice="N4")
    assert posizioni.aliquota_per(tedesco, s["bene"], n4) == n4                       # un'esenzione resta
    f = Fattura.objects.create(azienda=s["azienda"], cliente=tedesco)
    assert RigaFattura.objects.create(fattura=f, prodotto=s["bene"]).aliquota.natura == "N3.2"


def test_scelta_per_il_cliente(client, s):
    rossi = _cliente(s, "Rossi", "IT", "12345678903")
    speciale = PosizioneFiscale.objects.create(nome="Edilizia in reverse charge")
    speciale.regole.create(tipo_prodotto="tutti", a_aliquota=AliquotaIva.objects.get(codice="N6.7"))
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "Fiscale" in client.get(f"/contatti/contatti/{rossi.pk}/").content.decode()
    client.post(f"/fatturazione/contatto/{rossi.pk}/posizione/", {"posizione": str(speciale.pk)})
    assert posizioni.posizione_di(rossi) == speciale
    f = Fattura.objects.create(azienda=s["azienda"], cliente=rossi)
    assert RigaFattura.objects.create(fattura=f, prodotto=s["bene"]).aliquota.natura == "N6.7"
    client.post(f"/fatturazione/contatto/{rossi.pk}/posizione/", {"posizione": "auto"})
    assert not PosizioneContatto.objects.exists() and posizioni.posizione_di(rossi) is None


def test_dichiarazione_d_intento(s):
    from fatturazione import fatturapa
    esportatore = _cliente(s, "Export Srl", "IT", "12345678903")
    d = DichiarazioneIntento.objects.create(azienda=s["azienda"], cliente=esportatore, protocollo="24123456789012345-000001",
                                            data_protocollo=OGGI, dal=OGGI.replace(month=1, day=1), al=OGGI.replace(month=12, day=31),
                                            plafond=Decimal("1500"))
    f = Fattura.objects.create(azienda=s["azienda"], cliente=esportatore)
    r = RigaFattura.objects.create(fattura=f, prodotto=s["bene"])
    assert r.aliquota.natura == "N3.5"
    f.ricalcola()
    operazioni.emetti(f)
    f.refresh_from_db()
    assert f.dichiarazione_intento == d and d.utilizzato == 1000 and d.residuo == 500
    _, xml = fatturapa.genera(f)
    assert b"<TipoDato>INTENTO</TipoDato>" in xml and b"24123456789012345-000001" in xml
    g = Fattura.objects.create(azienda=s["azienda"], cliente=esportatore)
    RigaFattura.objects.create(fattura=g, prodotto=s["bene"])
    g.ricalcola()
    with pytest.raises(ValidationError, match="plafond"):
        operazioni.emetti(g)


def test_listino_iva_inclusa(s):
    from vendite.models import OrdineVendita, RigaVendita
    pubblico = Listino.objects.create(azienda=s["azienda"], nome="Pubblico", iva_inclusa=True)
    PrezzoListino.objects.create(listino=pubblico, prodotto=s["bene"], prezzo=Decimal("1220"))
    o = OrdineVendita.objects.create(azienda=s["azienda"], cliente=_cliente(s, "Mario"), listino=pubblico)
    r = RigaVendita.objects.create(ordine=o, prodotto=s["bene"], quantita=1)
    assert r.prezzo == Decimal("1000.0000") and r.aliquota.codice == "22"
