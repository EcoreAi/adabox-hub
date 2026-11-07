"""Distinte: candidati dalle scadenze aperte, file SEPA validati con gli XSD ISO (le due versioni), RiBa CBI a 120
caratteri, esiti che registrano o annullano incassi e pagamenti, niente scadenze in due distinte, pagine."""
import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from lxml import etree

from banca.models import Conto, iban_valido
from contatti.models import Contatto
from core.models import Azienda
from distinte import sepa, servizi
from distinte.models import ConfigConto, CoordinateBancarie, Distinta, Mandato, VoceDistinta
from distinte.testo import calcola_id_creditore, fisso, id_creditore_valido
from distinte.testo import sepa as pulisci_sepa
from fatturazione.models import Fattura, Incasso, Scadenza
from sdi.models import FatturaPassiva, ScadenzaPassiva

D = Decimal
DOPODOMANI = datetime.date.today() + datetime.timedelta(days=2)


def _iban(abi, cab, conto, cin="X"):
    bban = f"{cin}{abi}{cab}{conto:0>12}"
    numeri = "".join(str(int(c, 36)) for c in bban + "IT00")
    iban = f"IT{98 - int(numeri) % 97:02d}{bban}"
    assert iban_valido(iban)
    return iban


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva, azienda.indirizzo, azienda.cap, azienda.citta = "01234567897", "Via Roma 1", "00100", "Roma"
    azienda.save()
    conto = Conto.objects.create(azienda=azienda, nome="Principale", iban=_iban("05428", "11101", "123456"), bic="BLOPIT22")
    ConfigConto.objects.create(conto=conto, codice_sia="A1B2C", id_creditore=calcola_id_creditore("01234567897"))
    return {"azienda": azienda, "conto": conto,
            "cliente": Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, partita_iva="12345678903",
                                               indirizzo="Via Po 3", cap="20100", citta="Milano", provincia="MI"),
            "fornitore": Contatto.objects.create(azienda=azienda, nome="Bianchi & Figli Spa", fornitore=True)}


def _passiva(s, importo="500.00", iban="", numero="A1"):
    f = FatturaPassiva.objects.create(azienda=s["azienda"], fornitore=s["fornitore"], numero=numero, data=datetime.date(2026, 10, 1),
                                      totale=D(importo), stato=FatturaPassiva.REGISTRATA, registrata_il=datetime.date(2026, 10, 2),
                                      nome_file="x.xml")
    return ScadenzaPassiva.objects.create(fattura=f, data=datetime.date(2026, 11, 30), importo=D(importo), modalita="MP05", iban=iban)


def _attiva(s, modalita, importo="1220.00", numero="FT/1"):
    f = Fattura.objects.create(azienda=s["azienda"], cliente=s["cliente"], numero=numero, data=datetime.date(2026, 10, 15))
    Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA, totale=D(importo))
    return Scadenza.objects.create(fattura=f, data=datetime.date(2026, 12, 31), importo=D(importo), modalita=modalita)


def _valida(xml, messaggio):
    assert sepa.schema(messaggio).validate(etree.fromstring(xml))


def test_testi_e_identificativo_del_creditore():
    assert pulisci_sepa("Bianchi & Figli S.p.A. — perché_sì") == "Bianchi Figli S.p.A. perche si"
    assert fisso("Società", 10) == "SOCIETA   " and fisso(42, 5, numerico=True) == "00042"
    assert id_creditore_valido("DE98ZZZ09999999999") and id_creditore_valido(calcola_id_creditore("01234567897"))
    assert not id_creditore_valido("DE97ZZZ09999999999")


@pytest.mark.parametrize("versione", [ConfigConto.ISO_2019, ConfigConto.ISO_2009])
def test_bonifici_ai_fornitori(s, versione):
    ConfigConto.objects.filter(conto=s["conto"]).update(versione_sepa=versione)
    con_iban = _passiva(s, iban=_iban("03069", "09606", "100000012345"))
    senza = _passiva(s, "80.00", numero="A2")
    candidati = {c.chiave: c for c in servizi.candidati(s["azienda"], Distinta.BONIFICI)}
    assert candidati[f"p{senza.pk}"].problema == "manca l'IBAN del fornitore"
    CoordinateBancarie.objects.create(contatto=s["fornitore"], iban=_iban("02008", "01600", "55"))
    assert not {c.chiave: c for c in servizi.candidati(s["azienda"], Distinta.BONIFICI)}[f"p{senza.pk}"].problema
    distinta = servizi.crea(s["azienda"], Distinta.BONIFICI, s["conto"], DOPODOMANI, [f"p{con_iban.pk}", f"p{senza.pk}"])
    assert distinta.totale == D("580.00") and servizi.candidati(s["azienda"], Distinta.BONIFICI) == []
    nome, xml, _ = servizi.file(distinta)
    messaggio = sepa.VERSIONI[versione]["bonifici"]
    _valida(xml, messaggio)
    assert nome.startswith(messaggio) and b"Bianchi Figli Spa" in xml and b"<CtrlSum>580.00</CtrlSum>" in xml
    with pytest.raises(ValidationError):
        servizi.pagata(distinta.voci.first())                                   # prima va presentata
    servizi.presenta(distinta)
    assert servizi.tutte_pagate(distinta) == 2
    con_iban.refresh_from_db()
    distinta.refresh_from_db()
    assert con_iban.pagata and FatturaPassiva.objects.get(pk=con_iban.fattura_id).pagata
    assert distinta.stato == Distinta.CHIUSA
    voce = distinta.voci.get(scadenza_passiva=senza)
    servizi.insoluta(voce, motivo="IBAN chiuso")
    senza.refresh_from_db()
    assert not senza.pagata and f"p{senza.pk}" in {c.chiave for c in servizi.candidati(s["azienda"], Distinta.BONIFICI)}


@pytest.mark.parametrize("versione", [ConfigConto.ISO_2019, ConfigConto.ISO_2009])
def test_addebiti_sdd(s, versione):
    ConfigConto.objects.filter(conto=s["conto"]).update(versione_sepa=versione)
    scadenza = _attiva(s, "MP19")
    assert servizi.candidati(s["azienda"], Distinta.SDD)[0].problema == "il cliente non ha un mandato SDD attivo"
    Mandato.objects.create(azienda=s["azienda"], contatto=s["cliente"], riferimento="MND-ROSSI-1",
                           iban=_iban("03069", "09606", "77"), data_firma=datetime.date(2025, 3, 1), schema=Mandato.B2B)
    _attiva(s, "MP05", numero="FT/2")                                           # bonifico, ma il cliente ha il mandato
    candidati = servizi.candidati(s["azienda"], Distinta.SDD)
    assert len(candidati) == 2 and [c.modalita_giusta for c in candidati] == [True, False]
    distinta = servizi.crea(s["azienda"], Distinta.SDD, s["conto"], DOPODOMANI, [f"a{scadenza.pk}"])
    _, xml, _ = servizi.file(distinta)
    _valida(xml, sepa.VERSIONI[versione]["sdd"])
    assert b"<Cd>B2B</Cd>" in xml and b"MND-ROSSI-1" in xml and calcola_id_creditore("01234567897").encode() in xml
    Distinta.objects.filter(pk=distinta.pk).update(data=datetime.date.today())
    distinta.refresh_from_db()
    with pytest.raises(ValidationError, match="giorno lavorativo dopo"):
        servizi.file(distinta)
    servizi.presenta(distinta)
    voce = servizi.pagata(distinta.voci.get(), datetime.date(2026, 12, 31))
    scadenza.refresh_from_db()
    assert scadenza.pagata and voce.incasso.metodo == "sdd" and voce.incasso.importo == D("1220.00")
    servizi.insoluta(voce, motivo="AM04 fondi insufficienti")
    scadenza.refresh_from_db()
    assert not scadenza.pagata and not Incasso.objects.filter(scadenza=scadenza).exists()


def test_riba_cbi(s):
    scadenza = _attiva(s, "MP12", "1000.50")
    assert servizi.candidati(s["azienda"], Distinta.RIBA)[0].problema.startswith("manca la banca")
    CoordinateBancarie.objects.create(contatto=s["cliente"], iban=_iban("03069", "09606", "4242"), banca="Intesa Milano")
    _attiva(s, "MP05", numero="FT/2")                                           # bonifico: non è una RiBa
    distinta = servizi.crea(s["azienda"], Distinta.RIBA, s["conto"], DOPODOMANI, [f"a{scadenza.pk}"])
    nome, contenuto, tipo = servizi.file(distinta)
    righe = contenuto.decode("ascii").split("\r\n")[:-1]
    assert tipo == "text/plain" and all(len(r) == 120 for r in righe)
    assert [r[1:3] for r in righe] == ["IB", "14", "20", "30", "40", "50", "51", "70", "EF"]
    disposizione = righe[1]
    assert disposizione[22:28] == "311226" and disposizione[33:46] == "0000000100050" and disposizione[46] == "-"
    assert disposizione[47:52] == "05428" and disposizione[69:74] == "03069" and disposizione[91:96] == "A1B2C"
    assert righe[0][3:8] == "A1B2C" and righe[-1][45:52] == "0000001" and righe[-1][82:89] == "0000009"
    assert "INTESA MILANO" in righe[4] and "ROSSI SRL" in righe[3]
    ConfigConto.objects.filter(conto=s["conto"]).update(codice_sia="")
    with pytest.raises(ValidationError, match="codice SIA"):
        servizi.file(distinta)


def test_pagine(client, superuser, s):
    scadenza = _passiva(s, iban=_iban("03069", "09606", "1"))
    pagina = client.get(reverse("distinte:nuova") + f"?tipo=bonifici&conto={s['conto'].pk}&data={DOPODOMANI}").content.decode()
    assert "Bianchi &amp; Figli Spa" in pagina and "Crea la distinta" in pagina
    risposta = client.post(reverse("distinte:nuova"), {"tipo": "bonifici", "conto": s["conto"].pk, "data": DOPODOMANI,
                                                       "scelte": [f"p{scadenza.pk}"]})
    distinta = Distinta.objects.get()
    assert risposta.url == reverse("distinte:distinte_dettaglio", args=[distinta.pk]) and distinta.utente == superuser
    dettaglio = client.get(risposta.url).content.decode()
    assert "Scarica il file per la banca" in dettaglio and "Segna come presentata" in dettaglio
    assert client.get(reverse("distinte:file", args=[distinta.pk]))["Content-Type"] == "application/xml"
    client.post(reverse("distinte:presenta", args=[distinta.pk]))
    client.post(reverse("distinte:esiti", args=[distinta.pk]), {"azione": "pagata", "voce": distinta.voci.get().pk,
                                                                "data": "2026-11-30"})
    scadenza.refresh_from_db()
    assert scadenza.pagata and scadenza.pagata_il == datetime.date(2026, 11, 30)
    assert "Distinte di pagamento" in client.get(reverse("banca:conti_dettaglio", args=[s["conto"].pk])).content.decode()
    client.post(reverse("distinte:config_conto", args=[s["conto"].pk]), {"codice_sia": "zz9", "id_creditore": "", "versione_sepa": "2019"})
    assert ConfigConto.objects.get(conto=s["conto"]).codice_sia == "A1B2C"     # SIA non valido: non salvato
    assert "Coordinate bancarie" in client.get(reverse("contatti:contatti_dettaglio", args=[s["cliente"].pk])).content.decode()
    client.post(reverse("distinte:coordinate", args=[s["cliente"].pk]), {"iban": "it60 x054 2811 1010 0000 0123 456", "banca": "BPM"})
    assert CoordinateBancarie.objects.get(contatto=s["cliente"]).iban == "IT60X0542811101000000123456"
    client.post(reverse("distinte:coordinate", args=[s["cliente"].pk]), {"iban": ""})
    assert not CoordinateBancarie.objects.exists()
    assert client.get(reverse("distinte:distinte_lista")).status_code == 200
    assert client.get(reverse("distinte:mandati_lista")).status_code == 200


def test_altra_azienda_non_vede_le_distinte(client, superuser, s):
    altra = Azienda.objects.create(nome="Altra")
    conto = Conto.objects.create(azienda=altra, nome="X", iban=_iban("05428", "11101", "9"))
    distinta = Distinta.objects.create(azienda=altra, tipo=Distinta.BONIFICI, conto=conto, data=DOPODOMANI)
    assert client.get(reverse("distinte:file", args=[distinta.pk])).status_code == 404
    assert VoceDistinta.objects.count() == 0
