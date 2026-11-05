"""Scadenziario a fasce e pacchetto per il commercialista."""
import datetime
import io
import zipfile
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

import fiscale
from banca.models import Conto, MovimentoBanca
from contatti.models import Contatto
from core.models import Azienda
from fatturazione import operazioni, scadenzario
from fatturazione.models import DatiFiscali, Fattura, RigaFattura, Scadenza
from fiscale.models import AliquotaIva
from sdi.models import FatturaPassiva, RiepilogoPassiva, ScadenzaPassiva

OGGI = timezone.localdate()


def giorni_fa(n):
    return OGGI - datetime.timedelta(days=n)


@pytest.mark.parametrize("giorni,attesa", [(-5, "a_scadere"), (0, "a_scadere"), (1, "f30"), (30, "f30"), (31, "f60"), (60, "f60"),
                                           (61, "f90"), (90, "f90"), (91, "oltre")])
def test_fasce_ai_confini(giorni, attesa):
    assert scadenzario.fascia(giorni_fa(giorni), OGGI) == attesa


def test_senza_data_non_e_scaduta():
    assert scadenzario.fascia(None, OGGI) == "a_scadere"


def test_tabella_somma_per_controparte_e_ordina():
    righe, totali = scadenzario.tabella([(1, "Piccola", giorni_fa(10), D(10)), (2, "Grande", giorni_fa(100), D(500)),
                                         (2, "Grande", OGGI, D(100)), (3, "Saldata", OGGI, D(0))], OGGI)
    assert [r["nome"] for r in righe] == ["Grande", "Piccola"]
    assert righe[0]["oltre"] == 500 and righe[0]["a_scadere"] == 100 and righe[0]["scaduto"] == 500
    assert totali["totale"] == 610 and totali["scaduto"] == 510 and totali["f30"] == 10


@pytest.fixture
def scena(db, client, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    call_command("loaddata", str(Path(fiscale.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva, azienda.indirizzo, azienda.cap, azienda.citta, azienda.provincia = (
        "01234567897", "Via Roma 1", "00100", "Roma", "RM")
    azienda.save()
    DatiFiscali.objects.create(azienda=azienda, iban="IT60X0542811101000000123456", banca="Banca")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", partita_iva="12345678903", codice_sdi="ABC1234",
                                      indirizzo="Via Po 2", cap="20100", citta="Milano", provincia="MI", cliente=True)
    fornitore = Contatto.objects.create(azienda=azienda, nome="Forniture Spa", partita_iva="12345678903", fornitore=True)
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    client.force_login(root)
    return {"azienda": azienda, "cliente": cliente, "fornitore": fornitore, "root": root}


def _emessa(s, prezzo="1000"):
    f = Fattura.objects.create(azienda=s["azienda"], cliente=s["cliente"])
    RigaFattura.objects.create(fattura=f, descrizione="Consulenza", prezzo=D(prezzo), aliquota=AliquotaIva.objects.get(codice="22"))
    f.ricalcola()
    operazioni.emetti(f)
    return Fattura.objects.get(pk=f.pk)


def _ricevuta(s, numero="F1", stato=FatturaPassiva.REGISTRATA, tipo="TD01", nome_file="IT0_F1.xml"):
    f = FatturaPassiva.objects.create(azienda=s["azienda"], fornitore=s["fornitore"], numero=numero, data=OGGI, totale=D(122),
                                      stato=stato, tipo_documento=tipo, nome_file=nome_file, registrata_il=OGGI)
    f.originale.save(Path(nome_file).name, ContentFile(b"<xml/>"), save=True)
    RiepilogoPassiva.objects.create(fattura=f, aliquota=D(22), imponibile=D(100), imposta=D(22))
    ScadenzaPassiva.objects.create(fattura=f, data=giorni_fa(45), importo=D(122))
    return f


def test_scadenzario_clienti_considera_il_residuo(client, scena):
    f = _emessa(scena)
    scadenza = f.scadenze.first()
    Scadenza.objects.filter(pk=scadenza.pk).update(data=giorni_fa(45))
    operazioni.incassa_fattura(f, D(220))
    pagina = client.get("/fatturazione/scadenzario/").content.decode()
    assert "Rossi Srl" in pagina and "1000,00" in pagina.replace(".", "")
    assert f"f_fattura__cliente={scena['cliente'].pk}" in pagina


def test_il_link_dello_scadenzario_filtra_davvero(client, scena):
    _emessa(scena)
    altro = Contatto.objects.create(azienda=scena["azienda"], nome="Altro Srl", partita_iva="12345678903", codice_sdi="ABC1234",
                                    indirizzo="Via Po 2", cap="20100", citta="Milano", provincia="MI", cliente=True)
    f = Fattura.objects.create(azienda=scena["azienda"], cliente=altro)
    RigaFattura.objects.create(fattura=f, descrizione="X", prezzo=D(10), aliquota=AliquotaIva.objects.get(codice="22"))
    f.ricalcola()
    operazioni.emetti(f)
    pagina = client.get(f"/fatturazione/scadenze/?f_pagata=0&f_fattura__cliente={scena['cliente'].pk}").content.decode()
    assert "Rossi Srl" in pagina and "Altro Srl" not in pagina.split("<table")[-1]


def test_bozze_e_pagate_non_contano(client, scena):
    Fattura.objects.create(azienda=scena["azienda"], cliente=scena["cliente"])
    f = _emessa(scena)
    operazioni.incassa_fattura(f, f.residuo)
    assert "Nessuna scadenza aperta" in client.get("/fatturazione/scadenzario/").content.decode()


def test_csv_dello_scadenzario(client, scena):
    _emessa(scena)
    risposta = client.get("/fatturazione/scadenzario/?formato=csv")
    testo = risposta.content.decode()
    assert risposta["Content-Type"].startswith("text/csv") and "Rossi Srl" in testo and "1220,00" in testo


def test_pdf_dello_scadenzario_o_messaggio(client, scena):
    _emessa(scena)
    risposta = client.get("/fatturazione/scadenzario/?formato=pdf")
    assert risposta.status_code == 302 or risposta.content.startswith(b"%PDF")


def test_scadenzario_fornitori_salta_note_di_credito_e_filtra(client, scena):
    _ricevuta(scena)
    _ricevuta(scena, numero="NC1", tipo="TD04", nome_file="IT0_NC1.xml")
    pagina = client.get("/sdi/scadenzario/").content.decode()
    assert "Forniture Spa" in pagina and "122,00" in pagina and "244,00" not in pagina
    assert f"f_fattura__fornitore={scena['fornitore'].pk}" in pagina
    assert client.get(f"/sdi/pagamenti/?f_pagata=0&f_fattura__fornitore={scena['fornitore'].pk}").status_code == 200


def test_scadenzario_solo_con_il_permesso(client, scena):
    u = User.objects.create_user("u", "u@example.com", "x")
    u.profilo.aziende.set([scena["azienda"]])
    client.force_login(u)
    assert client.get("/fatturazione/scadenzario/").status_code == 403
    assert client.get("/sdi/scadenzario/").status_code == 403
    assert client.get("/fatturazione/commercialista/").status_code == 403


def _zip(client, **dati):
    risposta = client.post("/fatturazione/commercialista/", dati)
    assert risposta.status_code == 200 and risposta["Content-Type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(risposta.content))


def test_il_pacchetto_contiene_vendite_acquisti_e_banca(client, scena):
    f = _emessa(scena)
    operazioni.incassa_fattura(f, D(100))
    _ricevuta(scena)
    conto = Conto.objects.create(azienda=scena["azienda"], nome="Principale", iban="IT60X0542811101000000123456")
    MovimentoBanca.objects.create(azienda=scena["azienda"], conto=conto, data=OGGI, importo=D(100), descrizione="Bonifico", impronta="a")
    archivio = _zip(client, anno=OGGI.year, mese=OGGI.month)
    nomi = archivio.namelist()
    assert {"vendite/registro-iva-vendite.csv", "vendite/incassi.csv", "vendite/crediti-aperti-oggi.csv", "acquisti/registro-acquisti.csv",
            "acquisti/debiti-aperti-oggi.csv", "acquisti/fatture-ricevute/IT0_F1.xml", "banca/movimenti.csv", "LEGGIMI.txt"} <= set(nomi)
    assert any(n.startswith("vendite/fatture-xml/") and n.endswith(".xml") for n in nomi)
    assert "Rossi Srl" in archivio.read("vendite/registro-iva-vendite.csv").decode("utf-8-sig")
    assert "ancora da abbinare: 1" in archivio.read("LEGGIMI.txt").decode("utf-8-sig")


def test_il_pacchetto_segnala_cio_che_non_include(client, scena):
    _ricevuta(scena, stato=FatturaPassiva.DA_VERIFICARE)
    Contatto.objects.filter(pk=scena["cliente"].pk).update(partita_iva="", codice_fiscale="")
    _emessa_senza_dati = Fattura.objects.create(azienda=scena["azienda"], cliente=scena["cliente"], stato=Fattura.EMESSA, numero="9/2026", data=OGGI)
    RigaFattura.objects.create(fattura=_emessa_senza_dati, descrizione="X", prezzo=D(10), aliquota=AliquotaIva.objects.get(codice="22"))
    archivio = _zip(client, anno=OGGI.year, mese=OGGI.month)
    leggimi = archivio.read("LEGGIMI.txt").decode("utf-8-sig")
    assert "F1" in leggimi and "da verificare" in leggimi and "9/2026" in leggimi
    assert "acquisti/registro-acquisti.csv" not in archivio.namelist()


def test_il_nome_del_fornitore_non_esce_dalla_cartella(client, scena):
    f = _ricevuta(scena)
    FatturaPassiva.objects.filter(pk=f.pk).update(nome_file="../../etc/passwd")
    nomi = _zip(client, anno=OGGI.year, mese=OGGI.month).namelist()
    assert "acquisti/fatture-ricevute/passwd" in nomi and not any(".." in n for n in nomi)


def test_il_pacchetto_e_solo_dell_azienda_corrente(client, scena):
    altra = Azienda.objects.create(nome="Altra")
    cliente = Contatto.objects.create(azienda=altra, nome="ALTRUI Srl", cliente=True)
    f = Fattura.objects.create(azienda=altra, cliente=cliente, stato=Fattura.EMESSA, numero="1/2026", data=OGGI)
    Scadenza.objects.create(fattura=f, data=OGGI, importo=D(50))
    archivio = _zip(client, anno=OGGI.year, mese="")
    assert not any(b"ALTRUI" in archivio.read(n) for n in archivio.namelist())


def test_periodo_vuoto_da_un_pacchetto_con_il_solo_leggimi(client, scena):
    archivio = _zip(client, anno=OGGI.year - 3, mese=1)
    assert archivio.namelist() == ["LEGGIMI.txt"]
