"""Banca: lettura degli estratti, nessun doppione, proposte e incassi veri, sempre reversibili."""
import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

import fiscale
from banca import abbina, estratti
from banca.models import Abbinamento, Conto, Importazione, MovimentoBanca, iban_valido
from contatti.models import Contatto
from core.models import Azienda
from fatturazione import operazioni as fatture
from fatturazione.models import Fattura, Incasso, RigaFattura
from fiscale.models import AliquotaIva
from sdi.models import FatturaPassiva, ScadenzaPassiva

IBAN = "IT60X0542811101000000123456"
G = datetime.date

CAMT = f"""<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt>
<Acct><Id><IBAN>{IBAN}</IBAN></Id></Acct>
<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">100.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-06-01</Dt></Dt></Bal>
<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1250.50</Amt><CdtDbtInd>CRDT</CdtDbtInd><Dt><Dt>2026-06-30</Dt></Dt></Bal>
<Ntry><Amt Ccy="EUR">1220.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts>BOOK</Sts><BookgDt><Dt>2026-06-10</Dt></BookgDt><ValDt><Dt>2026-06-11</Dt></ValDt><AcctSvcrRef>REF1</AcctSvcrRef>
 <NtryDtls><TxDtls><RltdPties><Dbtr><Nm>Rossi Srl</Nm></Dbtr><DbtrAcct><Id><IBAN>IT10</IBAN></Id></DbtrAcct></RltdPties><RmtInf><Ustrd>Saldo fattura 1/2026</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>
<Ntry><Amt Ccy="EUR">5.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts>BOOK</Sts><BookgDt><Dt>2026-06-12</Dt></BookgDt><AddtlNtryInf>Commissioni</AddtlNtryInf></Ntry>
<Ntry><Amt Ccy="EUR">9.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><Sts>PDNG</Sts><BookgDt><Dt>2026-06-13</Dt></BookgDt></Ntry>
</Stmt></BkToCstmrStmt></Document>""".encode()


@pytest.fixture
def s(db):
    call_command("loaddata", str(Path(fiscale.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, partita_iva="12345678903")
    fornitore = Contatto.objects.create(azienda=azienda, nome="Verdi Forniture", fornitore=True)
    conto = Conto.objects.create(azienda=azienda, nome="Principale", iban=IBAN)
    return {"az": azienda, "cliente": cliente, "fornitore": fornitore, "conto": conto, "io": User.objects.create_superuser("root", "r@example.com", "x")}


def _fattura(s, prezzo=1000, cliente=None):
    f = Fattura.objects.create(azienda=s["az"], cliente=cliente or s["cliente"])
    RigaFattura.objects.create(fattura=f, descrizione="Prova", prezzo=D(prezzo), aliquota=AliquotaIva.objects.get(codice="22"))
    f.ricalcola()
    fatture.emetti(f)
    return f


def _mov(s, importo, descrizione="", controparte="", data=G(2026, 6, 10)):
    return MovimentoBanca.objects.create(azienda=s["az"], conto=s["conto"], data=data, importo=D(importo), descrizione=descrizione, controparte=controparte, impronta=f"{importo}{descrizione}{data}{MovimentoBanca.objects.count()}")


def _passiva(s, importo=100):
    f = FatturaPassiva.objects.create(azienda=s["az"], fornitore=s["fornitore"], numero="F7", data=G(2026, 6, 1), totale=D(importo), nome_file="x.xml")
    return ScadenzaPassiva.objects.create(fattura=f, data=G(2026, 6, 30), importo=D(importo))


# ---------- lettura

def test_camt():
    e = estratti.leggi(CAMT)
    assert e.formato == "CAMT" and e.iban == IBAN and e.saldo == D("1250.50") and e.saldo_al == G(2026, 6, 30)
    assert [r.importo for r in e.righe] == [D("1220.00"), D("-5.00")]              # quello in sospeso non c'è
    r = e.righe[0]
    assert r.data == G(2026, 6, 10) and r.valuta == G(2026, 6, 11) and r.controparte == "Rossi Srl" and "1/2026" in r.descrizione and r.riferimento == "REF1"
    assert e.righe[1].descrizione == "Commissioni"


def test_camt_piu_dettagli_nella_stessa_voce():
    xml = b"""<D><Stmt><Ntry><Amt>30.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-06-01</Dt></BookgDt><NtryDtls>
    <TxDtls><Amt>10.00</Amt><RmtInf><Ustrd>uno</Ustrd></RmtInf></TxDtls><TxDtls><Amt>20.00</Amt><RmtInf><Ustrd>due</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry></Stmt></D>"""
    assert [(r.importo, r.descrizione) for r in estratti.leggi(xml).righe] == [(D(10), "uno"), (D(20), "due")]


def test_xml_pericoloso_o_estraneo():
    bomba = b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "' + b"x" * 10 + b'"><!ENTITY b "&a;&a;&a;">]><Document><Stmt><Ntry><Amt>1.00</Amt><CdtDbtInd>CRDT</CdtDbtInd><BookgDt><Dt>2026-01-01</Dt></BookgDt><AddtlNtryInf>&b;</AddtlNtryInf></Ntry></Stmt></Document>'
    e = estratti.leggi(bomba)
    assert "xxx" not in e.righe[0].descrizione
    with pytest.raises(estratti.EstrattoNonValido):
        estratti.leggi(b"<Document><Altro/></Document>")
    with pytest.raises(estratti.EstrattoNonValido):
        estratti.leggi(b"<rotto")


@pytest.mark.parametrize("testo,atteso", [("1.234,56", "1234.56"), ("-1.234,56", "-1234.56"), ("1,234.56", "1234.56"), ("1234.56", "1234.56"), ("1234,5", "1234.50"),
                                          ("(12,00)", "-12.00"), ("+12 €", "12.00"), ("1.234", "1234.00"), ("12.50-", "-12.50"), ("0,05", "0.05")])
def test_importi(testo, atteso):
    assert estratti._importo(testo) == D(atteso)


def test_csv_con_preambolo_dare_avere_e_righe_sporche():
    csv = """Estratto conto;;;;
Intestatario: Azienda;;;;

Data contabile;Data valuta;Descrizione;Dare;Avere
10/06/2026;11/06/2026;Bonifico da Rossi fattura 1/2026;;1.220,00
12/06/2026;12/06/2026;Commissioni;5,00;
data sbagliata;;Riga rotta;;1,00
;;Saldo finale;;1.215,00
""".encode("cp1252")
    e = estratti.leggi(csv)
    assert e.formato == "CSV" and [r.importo for r in e.righe] == [D("1220.00"), D("-5.00")] and e.scartate == 1
    assert e.righe[0].valuta == G(2026, 6, 11)


def test_csv_con_virgole_e_importo_unico():
    csv = b'Date,Description,Amount\n2026-06-10,"Pagamento, fattura",1220.00\n2026-06-11,Spesa,-5.5\n'
    assert [r.importo for r in estratti.leggi(csv).righe] == [D("1220.00"), D("-5.50")]


def test_excel():
    import io

    from openpyxl import Workbook
    w = Workbook()
    w.active.append(["Data", "Causale", "Importo"])
    w.active.append([datetime.datetime(2026, 6, 10), "Incasso", 1220.5])
    b = io.BytesIO()
    w.save(b)
    e = estratti.leggi(b.getvalue())
    assert e.formato == "Excel" and e.righe[0].data == G(2026, 6, 10) and e.righe[0].importo == D("1220.50")


def test_file_non_valido():
    for contenuto in (b"", b"niente di utile\nqui", b"a;b;c\n1;2;3\n"):
        with pytest.raises(estratti.EstrattoNonValido):
            estratti.leggi(contenuto)


# ---------- importazione

def test_reimportare_non_duplica_ma_due_uguali_restano_due(s):
    csv = "Data;Descrizione;Importo\n10/06/2026;Caffè;-1,50\n10/06/2026;Caffè;-1,50\n".encode()
    prima = abbina.importa(s["conto"], csv, "a.csv")
    assert prima.nuovi == 2
    dopo = abbina.importa(s["conto"], csv, "a.csv")
    assert dopo.nuovi == 0 and dopo.doppi == 2 and MovimentoBanca.objects.count() == 2


def test_camt_di_un_altro_conto_rifiutato_e_saldo_aggiornato(s):
    abbina.importa(s["conto"], CAMT, "e.xml")
    s["conto"].refresh_from_db()
    assert s["conto"].saldo == D("1250.50")
    altro = Conto.objects.create(azienda=s["az"], nome="Altro", iban="IT60X0542811101000000654321")
    with pytest.raises(estratti.EstrattoNonValido):
        abbina.importa(altro, CAMT, "e.xml")
    assert not altro.movimenti.exists()


def test_iban():
    assert iban_valido(IBAN) and not iban_valido("IT60X0542811101000000123457") and not iban_valido("ciao")
    with pytest.raises(ValidationError) as e:
        Conto(nome="x", iban="IT00").clean()
    assert "iban" in e.value.message_dict
    c = Conto(nome="x", iban="it60 x054 2811 1010 0000 0123 456")
    c.clean()
    assert c.iban == IBAN


# ---------- proposte

def test_proposta_sicura_numero_e_importo(s):
    f = _fattura(s)
    m = _mov(s, f.totale, f"Bonifico saldo fattura {f.numero}", "Rossi Srl")
    lista = abbina.proposte(m, abbina.aperte_attive(s["az"]), abbina.aperte_passive(s["az"]))
    assert lista[0].scadenza.fattura == f and abbina.e_sicura(lista) and any("Numero" in x for x in lista[0].motivi)


@pytest.mark.parametrize("numero,testo,atteso", [("12/2026", "fattura 12/2026 saldo", True), ("12/2026", "FT 12-2026", True), ("12/2026", "fatt.12 2026", True),
                                                 ("12/2026", "fattura 112/2026", False), ("12/2026", "fattura 12/20265", False), ("1/2026", "11/2026", False)])
def test_numero_nel_testo(numero, testo, atteso):
    assert abbina._numero_nel_testo(numero, testo) is atteso


def test_due_fatture_uguali_non_sono_sicure(s):
    _fattura(s), _fattura(s)
    m = _mov(s, D("1220.00"), "Bonifico", "Rossi Srl")
    lista = abbina.proposte(m, abbina.aperte_attive(s["az"]), [])
    assert len(lista) == 2 and not abbina.e_sicura(lista)


def test_uscite_guardano_i_fornitori_ed_entrate_i_clienti(s):
    _fattura(s)
    sp = _passiva(s)
    lista = abbina.proposte(_mov(s, -100, "Pagamento F7"), abbina.aperte_attive(s["az"]), abbina.aperte_passive(s["az"]))
    assert lista[0].scadenza == sp and lista[0].passiva


def test_nessuna_proposta_se_non_somiglia(s):
    _fattura(s)
    assert not abbina.proposte(_mov(s, 33, "Altro"), abbina.aperte_attive(s["az"]), [])


# ---------- abbinare

def test_abbina_crea_l_incasso_vero_e_annulla_lo_toglie(s):
    f = _fattura(s)
    sc = f.scadenze.get()
    m = _mov(s, f.totale, "x")
    abbina.abbina(m, [f"a{sc.pk}"], s["io"])
    f.refresh_from_db(), m.refresh_from_db()
    assert f.pagata and m.stato == MovimentoBanca.ABBINATO
    i = Incasso.objects.get()
    assert i.data == m.data and i.importo == f.totale
    abbina.annulla(m.abbinamenti.get())
    f.refresh_from_db(), m.refresh_from_db()
    assert not f.pagata and m.stato == MovimentoBanca.DA_ABBINARE and not Incasso.objects.exists()


def test_annullare_l_incasso_da_fatturazione_riapre_il_movimento(s):
    f = _fattura(s)
    m = _mov(s, f.totale, "x")
    abbina.abbina(m, [f"a{f.scadenze.get().pk}"])
    fatture.annulla_incasso(Incasso.objects.get())
    m.refresh_from_db()
    assert m.stato == MovimentoBanca.DA_ABBINARE and not Abbinamento.objects.exists()


def test_pagamento_parziale_e_movimento_piu_grande(s):
    f = _fattura(s)
    m = _mov(s, 500, "acconto")
    abbina.abbina(m, [f"a{f.scadenze.get().pk}"])
    sc = f.scadenze.get()
    m.refresh_from_db()
    assert sc.incassato == D(500) and not sc.pagata and m.stato == MovimentoBanca.ABBINATO
    grande = _mov(s, 9999, "troppo")
    abbina.abbina(grande, [f"a{sc.pk}"])
    grande.refresh_from_db(), sc.refresh_from_db()
    assert sc.pagata and grande.stato == MovimentoBanca.PARZIALE and grande.da_coprire == D(9999) - D(720)


def test_un_bonifico_per_piu_fatture(s):
    a, b = _fattura(s), _fattura(s)
    m = _mov(s, a.totale + b.totale, "due fatture")
    abbina.abbina(m, [f"a{a.scadenze.get().pk}", f"a{b.scadenze.get().pk}"])
    a.refresh_from_db(), b.refresh_from_db(), m.refresh_from_db()
    assert a.pagata and b.pagata and m.stato == MovimentoBanca.ABBINATO and m.abbinamenti.count() == 2


def test_passiva_per_intero_e_annullo(s):
    sp = _passiva(s)
    with pytest.raises(ValidationError):
        abbina.abbina(_mov(s, -50, "poco"), [f"p{sp.pk}"])
    sp.refresh_from_db()
    assert not sp.pagata
    m = _mov(s, -100, "ok", data=G(2026, 6, 20))
    abbina.abbina(m, [f"p{sp.pk}"])
    sp.refresh_from_db(), sp.fattura.refresh_from_db()
    assert sp.pagata and sp.pagata_il == G(2026, 6, 20) and sp.fattura.pagata
    abbina.annulla(m.abbinamenti.get())
    sp.refresh_from_db(), sp.fattura.refresh_from_db(), m.refresh_from_db()
    assert not sp.pagata and not sp.fattura.pagata and m.stato == MovimentoBanca.DA_ABBINARE


def test_rifiuti(s):
    f = _fattura(s)
    sp = _passiva(s)
    entra, esce = _mov(s, 10, "e"), _mov(s, -10, "u")
    for m, chiave in ((entra, f"p{sp.pk}"), (esce, f"a{f.scadenze.get().pk}"), (entra, "a999999"), (entra, "zz"), (entra, "a")):
        with pytest.raises(ValidationError):
            abbina.abbina(m, [chiave])
    with pytest.raises(ValidationError):
        abbina.abbina(entra, [])
    abbina.ignora(entra)
    with pytest.raises(ValidationError):
        abbina.abbina(entra, [f"a{f.scadenze.get().pk}"])
    assert not Incasso.objects.exists()


def test_altra_azienda_non_si_tocca(s):
    altra = Azienda.objects.create(nome="Altra")
    c = Contatto.objects.create(azienda=altra, nome="Suo", cliente=True, partita_iva="12345678903")
    f = Fattura.objects.create(azienda=altra, cliente=c)
    RigaFattura.objects.create(fattura=f, descrizione="x", prezzo=D(10), aliquota=AliquotaIva.objects.get(codice="22"))
    f.ricalcola()
    fatture.emetti(f)
    with pytest.raises(ValidationError):
        abbina.abbina(_mov(s, 12, "x"), [f"a{f.scadenze.get().pk}"])
    assert not abbina.aperte_attive(s["az"])


def test_sicuri_solo_quelli_e_una_volta(s):
    a, b = _fattura(s), _fattura(s, 500)
    _mov(s, a.totale, f"fattura {a.numero}")
    _mov(s, a.totale, f"fattura {a.numero} doppio bonifico")
    dubbio = _mov(s, b.totale, "pagamento senza numero", "Rossi Srl")
    assert abbina.abbina_i_sicuri(s["az"]) == 1
    a.refresh_from_db(), b.refresh_from_db(), dubbio.refresh_from_db()
    assert a.pagata and not b.pagata and dubbio.stato == MovimentoBanca.DA_ABBINARE and Incasso.objects.count() == 1


# ---------- pagine

def test_pagine_permessi_e_flusso(s, client):
    f = _fattura(s)
    anna = User.objects.create_user("anna", "a@example.com", "x")
    client.force_login(anna)
    for url in ("riconcilia", "importa"):
        assert client.get(f"/banca/{url}/").status_code == 403
    client.force_login(s["io"])
    assert client.get("/banca/importa/").status_code == 200
    csv = f"Data;Descrizione;Importo\n10/06/2026;Saldo fattura {f.numero} <script>;{f.totale}\n".replace(".", ",").encode()
    r = client.post("/banca/importa/", {"conto": s["conto"].pk, "file": SimpleUploadedFile("e.csv", csv)})
    assert r.status_code == 302 and Importazione.objects.get().nuovi == 1
    html = client.get("/banca/riconcilia/").content.decode()
    assert "Stesso importo" in html and "Conferma i 1 sicuri" in html and "<script>" not in html.split("<main", 1)[-1].split("</main>")[0]
    m = MovimentoBanca.objects.get()
    assert client.get(f"/banca/movimento/{m.pk}/scegli/", {"q": "rossi"}).status_code == 200
    assert client.post(f"/banca/movimento/{m.pk}/abbina/", {"scadenza": f"a{f.scadenze.get().pk}"}).status_code == 302
    f.refresh_from_db()
    assert f.pagata
    assert "Togli" in client.get(f"/banca/movimenti/{m.pk}/").content.decode()
    assert client.get("/banca/movimenti/").status_code == 200
    assert client.get("/banca/movimenti/nuovo/").status_code == 403
    client.post(f"/banca/abbinamento/{m.abbinamenti.get().pk}/annulla/")
    f.refresh_from_db()
    assert not f.pagata
    assert client.get(f"/banca/movimento/{m.pk}/abbina/").status_code == 405
    client.post(f"/banca/movimento/{m.pk}/ignora/")
    m.refresh_from_db()
    assert m.stato == MovimentoBanca.IGNORATO
    client.post(f"/banca/movimento/{m.pk}/ripristina/")
    m.refresh_from_db()
    assert m.stato == MovimentoBanca.DA_ABBINARE


def test_importa_errori_chiari(s, client):
    client.force_login(s["io"])
    r = client.post("/banca/importa/", {"conto": s["conto"].pk, "file": SimpleUploadedFile("e.csv", b"niente;utile\n1;2\n")}, follow=True)
    assert "Non trovo le colonne" in r.content.decode() and not MovimentoBanca.objects.exists()
    r = client.post("/banca/importa/", {"file": SimpleUploadedFile("e.csv", b"x")}, follow=True)
    assert "Scegli il conto" in r.content.decode()


# ---------- MT940 e CBI

MT940 = """{1:F01UNCRITMMAXXX0000000000}{2:I940UNCRITMMAXXXN}{4:
:20:STARTUMS
:25:UNCRITMM/IT60X0542811101000000123456
:28C:00001/001
:60F:C260601EUR100,00
:61:2606100610C1220,00NTRFNONREF//REF1
Saldo fattura 1/2026
:86:/ORDP//NAME/ROSSI SRL/REMI/Saldo fattura 1/2026/EREF/E2E1
:61:2606120612D5,00NCHGNONREF
:86:Commissioni
:61:2606150615RD3,50NTRF//STORNO
:86:?00STORNO?20EREF+ABC?21SVWZ+Storno addebito?31IT10X0542811101000000654321?32BANCA
:62F:C260630EUR1318,50
-}"""


def test_mt940():
    e = estratti.leggi(MT940.encode())
    assert e.formato == "MT940" and e.iban == IBAN and e.saldo == D("1318.50") and e.saldo_al == G(2026, 6, 30)
    assert [r.importo for r in e.righe] == [D("1220.00"), D("-5.00"), D("3.50")]
    a, b, c = e.righe
    assert a.data == G(2026, 6, 10) and a.valuta == G(2026, 6, 10) and a.descrizione == "Saldo fattura 1/2026" and a.controparte == "ROSSI SRL" and a.riferimento == "REF1"
    assert b.descrizione == "Commissioni" and b.riferimento == ""
    assert c.descrizione == "Storno addebito" and c.controparte == "BANCA" and c.riferimento == "STORNO" and c.iban_controparte == "IT10X0542811101000000654321"


def test_mt940_senza_blocchi_swift_e_anno_a_cavallo():
    testo = ":20:X\n:25:IT60X0542811101000000123456\n:60F:C261231EUR10,00\n:61:2701021231D1,00NMSC\n:86:ultima dell'anno\n:62F:C270102EUR9,00\n"
    e = estratti.leggi(testo.encode())
    assert e.righe[0].valuta == G(2027, 1, 2) and e.righe[0].data == G(2026, 12, 31) and e.righe[0].importo == D("-1.00")


def test_mt940_che_non_torna_non_si_importa():
    with pytest.raises(estratti.EstrattoNonValido) as err:
        estratti.leggi(MT940.replace("EUR1318,50", "EUR1000,00").encode())
    assert "non torna" in str(err.value) and "1.318,50" in str(err.value) and "1.000,00" in str(err.value)
    with pytest.raises(estratti.EstrattoNonValido) as err:
        estratti.leggi(MT940.replace(":62F:C260630EUR1318,50\n", "").encode())
    assert "manca il saldo" in str(err.value)
    with pytest.raises(estratti.EstrattoNonValido) as err:
        estratti.leggi(MT940.replace(":61:2606120612D5,00NCHGNONREF", ":61:boh").encode())
    assert "non leggibile" in str(err.value)


def test_mt940_piu_estratti_nello_stesso_file():
    due = MT940 + "\n:20:SECONDO\n:25:IT60X0542811101000000123456\n:60F:C260630EUR1318,50\n:61:2607010701C1,00NTRFNONREF\n:86:x\n:62F:C260701EUR1319,50\n"
    e = estratti.leggi(due.encode())
    assert len(e.righe) == 4 and e.saldo == D("1319.50") and e.saldo_al == G(2026, 7, 1)


def _cbi(righe):
    return "\r\n".join(r.ljust(120) for r in righe).encode("cp1252")


def _record_61(abi="05428", cab="11101", conto="000000123456", saldo="000000000010000"):
    return " 61" + "0000001" + "     " + abi + "EUR" + "010626" + "C" + saldo + cab + conto + "12345678903     "


def _record_62(n, valuta, contabile, segno, importo, causale="48", rif_banca="", assegno=""):
    return f" 62{n:07d}{valuta}{contabile}{segno}{importo}{causale}000{assegno:<16}{rif_banca:<16}{'':<16}"


CBI = [
    " RH05428" + "12345" + "030726" + "ESTRATTO CONTO      ",
    _record_61(),
    _record_62(2, "110626", "100626", "C", "000000000122000", "48", "REF1"),
    " 630000003ZZZSaldo fattura 1/2026 ROSSI SRL",
    " 630000004IB1IT10X0542811101000000654321",
    " 630000005ID E2E-123",
    _record_62(6, "120626", "120626", "D", "000000000000500", "16"),
    " 630000007ZZZCommissioni",
    _record_62(8, "150626", "150626", "D", "000000000001000", "26"),
    " 640000009EUR300626C000000000130500",
    " 650000010EUR300626C000000000130500",
    " EF05428" + "12345" + "030726",
]


def test_cbi():
    e = estratti.leggi(_cbi(CBI))
    assert e.formato == "CBI" and e.coordinate == ("05428", "11101", "000000123456") and e.saldo == D("1305.00") and e.saldo_al == G(2026, 6, 30)
    assert [r.importo for r in e.righe] == [D("1220.00"), D("-5.00"), D("-10.00")]
    a, b, c = e.righe
    assert a.data == G(2026, 6, 10) and a.valuta == G(2026, 6, 11) and a.descrizione == "Saldo fattura 1/2026 ROSSI SRL"
    assert a.riferimento == "REF1" and a.iban_controparte == "IT10X0542811101000000654321"
    assert b.descrizione == "Commissioni" and c.descrizione == "Causale CBI 26"
    assert e.righe[1].riferimento == ""
    assert estratti.leggi(_cbi(CBI[1:-1])).formato == "CBI"             # anche senza testa e coda


def test_cbi_che_non_torna_o_rotto_non_si_importa():
    with pytest.raises(estratti.EstrattoNonValido) as err:
        estratti.leggi(_cbi(CBI[:-3] + [" 640000009EUR300626C000000000130000"] + CBI[-2:]))
    assert "non torna" in str(err.value) and "1.305,00" in str(err.value) and "1.300,00" in str(err.value)
    with pytest.raises(estratti.EstrattoNonValido) as err:
        estratti.leggi(_cbi([r for r in CBI if not r.startswith(" 64")]))
    assert "manca il record del saldo" in str(err.value)
    with pytest.raises(estratti.EstrattoNonValido) as err:
        estratti.leggi(_cbi(CBI[:2] + [" 620000002rotto"] + CBI[3:]))
    assert "Riga 3" in str(err.value)
    with pytest.raises(estratti.EstrattoNonValido):
        estratti.leggi(_cbi(CBI[:2] + [" 99strano"] + CBI[2:]))


def test_cbi_di_un_altro_conto_rifiutato(s):
    abbina.importa(s["conto"], _cbi(CBI), "e.txt")
    assert MovimentoBanca.objects.count() == 3
    altro = Conto.objects.create(azienda=s["az"], nome="Altro", iban="IT60X0542811101000000654321")
    with pytest.raises(estratti.EstrattoNonValido) as err:
        abbina.importa(altro, _cbi(CBI), "e.txt")
    assert "123456" in str(err.value) and not altro.movimenti.exists()
    abbina.importa(altro, _cbi([_record_61(conto="000000654321")] + CBI[2:]), "e.txt")
    assert altro.movimenti.count() == 3


def test_mt940_di_un_altro_conto_rifiutato(s):
    altro = Conto.objects.create(azienda=s["az"], nome="Altro", iban="IT60X0542811101000000654321")
    with pytest.raises(estratti.EstrattoNonValido):
        abbina.importa(altro, MT940.encode(), "e.sta")
    assert abbina.importa(s["conto"], MT940.encode(), "e.sta").nuovi == 3
