"""Riscontro a tre, resi, riordino e valutazione dei fornitori."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.utils import timezone

import fiscale
import prodotti
from acquisti import operazioni, riordino, riscontro, valutazione
from acquisti.models import FatturaOrdine, OrdineAcquisto, RegolaRiordino, RigaAcquisto, VoceListino
from contatti.models import Contatto
from core.models import Azienda
from magazzino import collegamenti, operazioni as magazzino
from magazzino.models import Consegna, Magazzino, Movimento, Ricevimento, RigaRicevimento
from prodotti.models import Prodotto
from sdi import passive
from sdi.models import FatturaPassiva


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    fornitore = Contatto.objects.create(azienda=azienda, nome="Grossista Spa", fornitore=True, partita_iva="01234567890",
                                        email="ordini@grossista.it")
    toner = Prodotto.objects.create(azienda=azienda, nome="Toner", costo=Decimal("10"), prezzo_vendita=Decimal("64"))
    return azienda, fornitore, toner


def _confermato(azienda, fornitore, prodotto, quantita=10, numero="OA/2026/0001", **campi):
    o = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, numero=numero, **campi)
    RigaAcquisto.objects.create(ordine=o, prodotto=prodotto, quantita=quantita)
    o.ricalcola()
    operazioni.conferma(o)
    o.refresh_from_db()
    return o


def _ricevi(ordine, quantita=None, data=None):
    r = collegamenti.di(ordine, Ricevimento).filter(stato=Ricevimento.BOZZA).first()
    if quantita is not None:
        RigaRicevimento.objects.filter(ricevimento=r).update(quantita=quantita)
    if data:
        Ricevimento.objects.filter(pk=r.pk).update(data=data)
        r.refresh_from_db()
    magazzino.ricevi(r)
    return r


def _fattura(azienda, fornitore, imponibile, numero="F1", tipo="TD01", causale=""):
    return FatturaPassiva.objects.create(azienda=azienda, fornitore=fornitore, numero=numero, tipo_documento=tipo,
                                         data=timezone.localdate(), causale=causale, imponibile=imponibile,
                                         imposta=imponibile * Decimal("0.22"), totale=imponibile * Decimal("1.22"),
                                         nome_file="f.xml", originale=ContentFile(b"<x/>", name="f.xml"))


# --- riscontro

def test_ordine_appena_confermato_e_tutto_da_ricevere(scena):
    o = _confermato(*scena)
    r = riscontro.riepilogo(o)
    assert r["stato_ricevimento"] == "da_ricevere" and r["stato_fatturazione"] == "da_fatturare"
    assert r["valore_ricevuto"] == 0 and r["ha_residuo"] and not r["ha_netto"]


def test_ricevuto_in_parte_e_ricevimento_del_residuo(scena):
    o = _confermato(*scena)
    _ricevi(o, 4)
    r = riscontro.riepilogo(o)
    assert r["stato_ricevimento"] == "parziale" and r["righe"][0]["residuo"] == 6 and r["valore_ricevuto"] == Decimal("40.00")
    residuo = riscontro.crea_residuo(o)
    assert residuo.righe.get().quantita == 6 and riscontro.crea_residuo(o) == residuo   # non ne crea un secondo
    magazzino.ricevi(residuo)
    assert riscontro.riepilogo(o)["stato_ricevimento"] == "ricevuto"
    with pytest.raises(ValidationError):
        riscontro.crea_residuo(o)


def test_stesso_prodotto_su_due_righe_a_prezzi_diversi(scena):
    azienda, fornitore, toner = scena
    o = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, numero="X")
    RigaAcquisto.objects.create(ordine=o, prodotto=toner, quantita=10, prezzo=Decimal("10"))
    RigaAcquisto.objects.create(ordine=o, prodotto=toner, quantita=10, prezzo=Decimal("20"))
    o.ricalcola()
    operazioni.conferma(o)
    _ricevi(o)
    r = riscontro.riepilogo(o)
    assert len(r["righe"]) == 1 and r["stato_ricevimento"] == "ricevuto" and r["valore_ricevuto"] == o.imponibile


def test_servizi_e_righe_libere_valgono_per_intero(scena):
    azienda, fornitore, _ = scena
    o = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, numero="X")
    RigaAcquisto.objects.create(ordine=o, descrizione="Trasporto", quantita=1, prezzo=Decimal("50"))
    o.ricalcola()
    operazioni.conferma(o)
    r = riscontro.riepilogo(o)
    assert r["stato_ricevimento"] == "ricevuto" and r["valore_ricevuto"] == Decimal("50.00")


def test_fattura_coerente_oltre_e_tolleranza(scena):
    azienda, fornitore, toner = scena
    o = _confermato(azienda, fornitore, toner)
    _ricevi(o)
    riscontro.collega(o, _fattura(azienda, fornitore, Decimal("100.50")))
    assert riscontro.riepilogo(o)["stato_fatturazione"] == "coerente"            # entro l'1% predefinito
    FatturaOrdine.objects.all().delete()
    riscontro.collega(o, _fattura(azienda, fornitore, Decimal("130"), numero="F2"))
    r = riscontro.riepilogo(o)
    assert r["stato_fatturazione"] == "oltre" and r["scostamento"] == Decimal("30.00")


def test_merce_non_arrivata_ma_fatturata_si_vede(scena):
    azienda, fornitore, toner = scena
    o = _confermato(azienda, fornitore, toner)
    _ricevi(o, 5)
    riscontro.collega(o, _fattura(azienda, fornitore, Decimal("100")))
    assert riscontro.riepilogo(o)["stato_fatturazione"] == "oltre"


def test_fattura_divisa_tra_due_ordini_senza_superare_il_totale(scena):
    azienda, fornitore, toner = scena
    a = _confermato(azienda, fornitore, toner, numero="A")
    b = _confermato(azienda, fornitore, toner, numero="B")
    f = _fattura(azienda, fornitore, Decimal("150"))
    riscontro.collega(a, f, Decimal("100"))
    with pytest.raises(ValidationError, match="restano da imputare 50"):
        riscontro.collega(b, f, Decimal("60"))
    assert riscontro.collega(b, f).importo == Decimal("50")


def test_fattura_di_altro_fornitore_e_ordine_non_confermato(scena):
    azienda, fornitore, toner = scena
    altro = Contatto.objects.create(azienda=azienda, nome="Altro", fornitore=True)
    o = _confermato(azienda, fornitore, toner)
    with pytest.raises(ValidationError):
        riscontro.collega(o, _fattura(azienda, altro, Decimal("10")))
    bozza = OrdineAcquisto.objects.create(azienda=azienda, fornitore=fornitore, numero="B")
    with pytest.raises(ValidationError):
        riscontro.collega(bozza, _fattura(azienda, fornitore, Decimal("10")))


def test_reso_con_nota_di_credito_torna_coerente(scena):
    azienda, fornitore, toner = scena
    o = _confermato(azienda, fornitore, toner)
    _ricevi(o)
    riscontro.collega(o, _fattura(azienda, fornitore, Decimal("100")))
    reso = riscontro.crea_reso(o)
    assert reso.causale_trasporto == "reso" and reso.cliente == fornitore and reso.righe.get().quantita == 10
    assert riscontro.crea_reso(o) == reso
    reso.righe.update(quantita=3)
    magazzino.spedisci(reso)
    assert reso.numero.startswith("DDT/")
    assert Movimento.objects.filter(prodotto=toner).order_by("pk").last().quantita == -3
    r = riscontro.riepilogo(o)
    assert r["righe"][0]["netto"] == 7 and r["stato_ricevimento"] == "parziale" and r["stato_fatturazione"] == "oltre"
    riscontro.collega(o, _fattura(azienda, fornitore, Decimal("30"), numero="NC1", tipo="TD04"))
    r = riscontro.riepilogo(o)
    assert r["fatturato"] == Decimal("70.00") and r["stato_fatturazione"] == "coerente"


def test_la_consegna_di_reso_non_blocca_ne_tocca_le_vendite(scena):
    o = _confermato(*scena)
    _ricevi(o)
    assert Consegna.objects.count() == 0
    riscontro.crea_reso(o)
    assert Consegna.objects.get().origine == o


XML = """<?xml version="1.0"?><p:FatturaElettronica xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">
<FatturaElettronicaHeader><CedentePrestatore><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>01234567890</IdCodice></IdFiscaleIVA><Anagrafica><Denominazione>Grossista Spa</Denominazione></Anagrafica></DatiAnagrafici></CedentePrestatore>
<CessionarioCommittente><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>{piva}</IdCodice></IdFiscaleIVA></DatiAnagrafici></CessionarioCommittente></FatturaElettronicaHeader>
<FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento><Data>2026-11-01</Data><Numero>{numero}</Numero><ImportoTotaleDocumento>122</ImportoTotaleDocumento>{causale}</DatiGeneraliDocumento>{riferimenti}</DatiGenerali>
<DatiBeniServizi><DettaglioLinee><NumeroLinea>1</NumeroLinea><Descrizione>Toner</Descrizione><PrezzoUnitario>10</PrezzoUnitario><PrezzoTotale>100</PrezzoTotale><AliquotaIVA>22</AliquotaIVA></DettaglioLinee>
<DatiRiepilogo><AliquotaIVA>22</AliquotaIVA><ImponibileImporto>100</ImponibileImporto><Imposta>22</Imposta></DatiRiepilogo></DatiBeniServizi></FatturaElettronicaBody></p:FatturaElettronica>"""


def _arriva(azienda, numero="F100", riferimenti="", causale=""):
    Azienda.objects.filter(pk=azienda.pk).update(partita_iva="09999999999")
    xml = XML.format(piva="09999999999", numero=numero, riferimenti=riferimenti, causale=causale).encode()
    return passive.importa(f"{numero}.xml", xml, azienda)[0][0]


def test_fattura_sdi_si_collega_da_sola_dal_numero_d_ordine(scena):
    azienda, fornitore, toner = scena
    o = _confermato(azienda, fornitore, toner)
    f = _arriva(azienda, riferimenti="<DatiOrdineAcquisto><IdDocumento>OA/2026/0001</IdDocumento></DatiOrdineAcquisto>")
    c = FatturaOrdine.objects.get()
    assert (c.ordine, c.fattura_id, c.importo, c.automatico) == (o, f.pk, Decimal("100.00"), True)


def test_fattura_sdi_si_collega_dal_ddt_del_fornitore(scena):
    azienda, fornitore, toner = scena
    o = _confermato(azienda, fornitore, toner)
    Ricevimento.objects.filter(riferimento=o.numero).update(ddt_fornitore="D77")
    _arriva(azienda, riferimenti="<DatiDDT><NumeroDDT>D77</NumeroDDT></DatiDDT>")
    assert FatturaOrdine.objects.get().ordine == o


def test_fattura_sdi_si_collega_dalla_causale(scena):
    azienda, fornitore, toner = scena
    o = _confermato(azienda, fornitore, toner)
    _arriva(azienda, causale="<Causale>Rif. vs ordine OA/2026/0001 del mese</Causale>")
    assert FatturaOrdine.objects.get().ordine == o


def test_fattura_senza_riferimenti_o_ordine_altrui_non_si_collega(scena):
    azienda, fornitore, toner = scena
    altro = Contatto.objects.create(azienda=azienda, nome="Altro", fornitore=True)
    _confermato(azienda, altro, toner, numero="OA/2026/0009")
    _arriva(azienda, numero="F1")
    _arriva(azienda, numero="F2", riferimenti="<DatiOrdineAcquisto><IdDocumento>OA/2026/0009</IdDocumento></DatiOrdineAcquisto>")
    assert not FatturaOrdine.objects.exists() and FatturaPassiva.objects.count() == 2


def test_un_errore_degli_acquisti_non_ferma_l_arrivo_della_fattura(scena, monkeypatch):
    azienda, fornitore, toner = scena
    _confermato(azienda, fornitore, toner)
    monkeypatch.setattr(riscontro, "_candidati", lambda *a: 1 / 0)
    _arriva(azienda, riferimenti="<DatiOrdineAcquisto><IdDocumento>OA/2026/0001</IdDocumento></DatiOrdineAcquisto>")
    assert FatturaPassiva.objects.count() == 1 and not FatturaOrdine.objects.exists()


def test_fattura_eliminata_toglie_il_collegamento(scena):
    azienda, fornitore, toner = scena
    o = _confermato(azienda, fornitore, toner)
    f = _fattura(azienda, fornitore, Decimal("10"))
    riscontro.collega(o, f)
    f.delete()
    assert not FatturaOrdine.objects.exists()


def test_pagina_ordine_e_collegamento_a_mano(client, superuser, scena):
    azienda, fornitore, toner = scena
    o = _confermato(azienda, fornitore, toner)
    f = _fattura(azienda, fornitore, Decimal("100"))
    pagina = client.get(f"/acquisti/ordini/{o.pk}/").content.decode()
    assert "Riscontro: ordine, merce, fattura" in pagina and "Collega una fattura" in pagina
    r = client.post("/acquisti/collega-fattura/", {"ordine": o.pk, "fattura": f.pk, "importo": "100,00"})
    assert r.status_code == 302 and FatturaOrdine.objects.get().importo == Decimal("100.00")
    assert "Grossista" in client.get(f"/sdi/passive/{f.pk}/").content.decode()
    c = FatturaOrdine.objects.get()
    client.post(f"/acquisti/scollega-fattura/{c.pk}/")
    assert not FatturaOrdine.objects.exists()


def test_collegamento_non_attraversa_le_aziende(client, scena):
    azienda, fornitore, toner = scena
    altra = Azienda.objects.create(nome="Altra Srl")
    forn2 = Contatto.objects.create(azienda=altra, nome="Suo", fornitore=True)
    o = _confermato(altra, forn2, Prodotto.objects.create(azienda=altra, nome="Suo", costo=1))
    f = _fattura(azienda, fornitore, Decimal("10"))
    u = User.objects.create_user("buyer", "b@example.com", "pass12345!")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=["acquisti", "sdi"]))
    u.profilo.aziende.add(azienda)
    client.force_login(u)
    assert client.post("/acquisti/collega-fattura/", {"ordine": o.pk, "fattura": f.pk}).status_code == 404
    assert client.get("/acquisti/riordino/").status_code == 200


def test_bottoni_residuo_e_reso_con_redirect(client, superuser, scena):
    o = _confermato(*scena)
    assert "bottone/rendi" not in client.get(f"/acquisti/ordini/{o.pk}/").content.decode()
    _ricevi(o, 4)
    pagina = client.get(f"/acquisti/ordini/{o.pk}/").content.decode()
    assert "bottone/rendi" in pagina and "bottone/ricevi_residuo" in pagina
    assert "/magazzino/ricevimenti/" in client.post(f"/acquisti/ordini/{o.pk}/bottone/ricevi_residuo/").url
    assert "/magazzino/consegne/" in client.post(f"/acquisti/ordini/{o.pk}/bottone/rendi/").url


# --- riordino

@pytest.fixture
def giacenza(scena):
    azienda, _, toner = scena
    Prodotto.objects.filter(pk=toner.pk).update(scorta_minima=Decimal("10"))
    toner.refresh_from_db()
    Movimento.objects.create(azienda=azienda, prodotto=toner, magazzino=Magazzino.predefinito_per(azienda),
                             quantita=Decimal("4"), tipo=Movimento.RETTIFICA)
    return toner


def test_sotto_scorta_con_fornitore_da_listino(scena, giacenza):
    azienda, fornitore, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("9"), quantita_minima=8)
    v = riordino.proposte(azienda)[0]
    assert (v["previsto"], v["fornitore"]) == (Decimal("4"), fornitore)
    assert v["quantita"] == Decimal("8")                 # ne servirebbero 6, ma il minimo del fornitore è 8


def test_regola_con_obiettivo_e_senza_scorta_minima(scena, giacenza):
    azienda, fornitore, toner = scena
    Prodotto.objects.filter(pk=toner.pk).update(scorta_minima=0)
    assert riordino.proposte(azienda) == []
    RegolaRiordino.objects.create(azienda=azienda, prodotto=toner, punto_riordino=Decimal("5"), scorta_obiettivo=Decimal("20"),
                                  fornitore=fornitore)
    v = riordino.proposte(azienda)[0]
    assert v["quantita"] == Decimal("16") and v["fornitore"] == fornitore


def test_in_arrivo_e_impegnato_cambiano_il_conto(scena, giacenza):
    azienda, fornitore, toner = scena
    _confermato(azienda, fornitore, toner, 20)          # ricevimento aperto: non serve riordinare
    assert riordino.proposte(azienda) == []
    c = Consegna.objects.create(azienda=azienda, magazzino=Magazzino.predefinito_per(azienda), cliente=fornitore)
    c.righe.create(prodotto=toner, quantita=Decimal("30"))
    assert riordino.proposte(azienda)[0]["previsto"] == Decimal("-6")


def test_creare_le_richieste_due_volte_non_fa_doppioni(scena, giacenza):
    azienda, fornitore, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("9"))
    ordini = riordino.crea_richieste(azienda, riordino.proposte(azienda))
    assert len(ordini) == 1 and ordini[0].stato == OrdineAcquisto.BOZZA and ordini[0].righe.get().quantita == 6
    assert ordini[0].righe.get().prezzo == Decimal("9") and ordini[0].numero.startswith("OA/")
    assert riordino.proposte(azienda) == []


def test_offerte_di_gara_non_contano_come_in_arrivo(scena, giacenza):
    from acquisti.models import Gara, RigaGara
    azienda, fornitore, toner = scena
    g = Gara.objects.create(azienda=azienda, titolo="T")
    g.fornitori.add(fornitore)
    RigaGara.objects.create(gara=g, prodotto=toner, quantita=100)
    operazioni.crea_offerte(g)
    assert riordino.proposte(azienda)[0]["in_arrivo"] == 0


def test_lavoro_automatico_solo_con_la_regola_che_lo_chiede(scena, giacenza):
    azienda, fornitore, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("9"))
    assert riordino.automatico() == 0
    RegolaRiordino.objects.create(azienda=azienda, prodotto=toner, punto_riordino=10, scorta_obiettivo=10, automatica=True)
    assert riordino.automatico() == 1
    assert riordino.automatico() == 0                     # la bozza creata conta già come in arrivo
    assert OrdineAcquisto.objects.get().stato == OrdineAcquisto.BOZZA


def test_senza_fornitore_si_segnala_e_non_si_crea(client, superuser, scena, giacenza):
    azienda, *_ = scena
    pagina = client.get("/acquisti/riordino/").content.decode()
    assert "senza fornitore" in pagina
    client.post("/acquisti/riordino/crea/", {"prodotto": giacenza.pk})
    assert not OrdineAcquisto.objects.exists()


def test_pagina_crea_solo_i_prodotti_scelti_e_ignora_quantita_inviate(client, superuser, scena, giacenza):
    azienda, fornitore, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, prezzo=Decimal("9"))
    client.post("/acquisti/riordino/crea/", {})
    assert not OrdineAcquisto.objects.exists()
    client.post("/acquisti/riordino/crea/", {"prodotto": toner.pk, "quantita": "99999"})
    assert OrdineAcquisto.objects.get().righe.get().quantita == 6


def test_riordino_separa_le_aziende(scena, giacenza):
    azienda, fornitore, toner = scena
    altra = Azienda.objects.create(nome="Altra Srl")
    assert riordino.proposte(altra) == []


# --- valutazione

def test_pagella_del_fornitore(client, superuser, scena):
    azienda, fornitore, toner = scena
    oggi = timezone.localdate()
    ieri, domani = oggi - datetime.timedelta(days=1), oggi + datetime.timedelta(days=1)
    puntuale = _confermato(azienda, fornitore, toner, numero="A", consegna_prevista=domani)
    _ricevi(puntuale, data=oggi)
    in_ritardo = _confermato(azienda, fornitore, toner, numero="B", consegna_prevista=ieri)
    _ricevi(in_ritardo, data=oggi)
    _confermato(azienda, fornitore, toner, numero="C", consegna_prevista=ieri)            # scaduto e mai arrivato
    _confermato(azienda, fornitore, toner, numero="D", consegna_prevista=domani)          # non ancora giudicabile
    reso = riscontro.crea_reso(puntuale)
    reso.righe.update(quantita=2)
    magazzino.spedisci(reso)
    riga = valutazione.schede(azienda, oggi - datetime.timedelta(days=30), oggi)[0]
    assert riga["fornitore"] == fornitore and riga["ordini"] == 4 and riga["misurati"] == 2 + 1
    assert riga["puntualita"] == 33                      # A è arrivato in tempo: il reso successivo pesa sui resi
    assert riga["resi"] == 10 and riga["completezza"] == 45
    assert riga["giorni"] == 0
    pagina = client.get("/acquisti/valutazione/").content.decode()
    assert "Grossista Spa" in pagina and "Puntualità" in pagina


def test_pagella_senza_ordini_e_date_sbagliate(client, superuser, scena):
    assert client.get("/acquisti/valutazione/?dal=boh&al=").status_code == 200


def test_utente_senza_azienda_non_vede_le_pagine(client, scena):
    u = User.objects.create_user("solo", "s@example.com", "pass12345!")
    u.user_permissions.add(Permission.objects.get(codename="view_ordineacquisto"))
    u.profilo.aziende.clear()
    client.force_login(u)
    assert client.get("/acquisti/riordino/").status_code == 403
    assert client.get("/acquisti/valutazione/").status_code == 403
