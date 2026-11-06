"""Liquidazione IVA dai registri: debito e credito, detraibilità, split, differita, autofatture, riporti, soglia,
interessi dei trimestrali, chiusura che congela i numeri, file LIPE e pagine."""
import datetime
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from django.urls import reverse

from contatti.models import Contatto
from core import parametri
from core.models import Azienda
from fatturazione.models import Fattura, Incasso, RigaFattura, Scadenza
from fiscale.models import AliquotaIva
from iva import calcolo, lipe
from iva.models import Detraibilita, Liquidazione
from sdi.models import FatturaPassiva, RiepilogoPassiva

D = Decimal
NS = {"iv": lipe.NS}
ANNO = datetime.date.today().year - 1                 # un anno chiuso: tutti i periodi esistono


def _piva_valida(base="0123456789"):
    return next(base + str(c) for c in range(10) if lipe.partita_iva_valida(base + str(c)))


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva = azienda.codice_fiscale = _piva_valida()
    azienda.save()
    return {"azienda": azienda, "cliente": Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True),
            "fornitore": Contatto.objects.create(azienda=azienda, nome="Bianchi Spa", fornitore=True)}


def _aliquota(codice="22", **modifiche):
    a = AliquotaIva.objects.filter(codice=codice).first() or AliquotaIva.objects.create(
        codice=codice, descrizione=f"Aliquota {codice}", percentuale=D(0) if codice.startswith("N") else D(codice),
        natura=codice if codice.startswith("N") else "")
    if modifiche:
        a.pk, a.codice = None, f"{codice}-{len(modifiche)}{''.join(modifiche.values())}"
        for k, v in modifiche.items():
            setattr(a, k, v)
        a.save()
    return a


def _vendita(s, mese, imponibile, aliquota=None, tipo="TD01", giorno=10, anno=ANNO):
    f = Fattura.objects.create(azienda=s["azienda"], cliente=s["cliente"], numero=f"FT/{Fattura.objects.count() + 1}",
                               data=datetime.date(anno, mese, giorno), tipo=tipo)
    RigaFattura.objects.create(fattura=f, descrizione="Servizio", prezzo=D(imponibile), aliquota=aliquota or _aliquota())
    f.ricalcola()
    Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA)
    return Fattura.objects.get(pk=f.pk)


def _acquisto(s, mese, imponibile, aliquota="22", natura="", esigibilita="I", nota_credito=False, detraibile=None):
    imponibile, aliquota = D(imponibile), D(aliquota)
    imposta = (imponibile * aliquota / 100).quantize(D("0.01"))
    f = FatturaPassiva.objects.create(azienda=s["azienda"], fornitore=s["fornitore"], numero=f"A{FatturaPassiva.objects.count() + 1}",
                                      data=datetime.date(ANNO, mese, 5), tipo_documento="TD04" if nota_credito else "TD01",
                                      imponibile=imponibile, imposta=imposta, totale=imponibile + imposta,
                                      stato=FatturaPassiva.REGISTRATA, registrata_il=datetime.date(ANNO, mese, 8), nome_file="x.xml")
    RiepilogoPassiva.objects.create(fattura=f, aliquota=aliquota, natura=natura, imponibile=imponibile, imposta=imposta,
                                    esigibilita=esigibilita)
    if detraibile is not None:
        Detraibilita.objects.create(fattura=f, percentuale=D(detraibile))
    return f


def test_debito_credito_e_detraibilita(s):
    _vendita(s, 1, "1000")                                         # 220 di IVA
    _vendita(s, 1, "200", tipo="TD04")                             # nota di credito: -44
    _vendita(s, 1, "300", aliquota=_aliquota("N3.1"))              # export: nei totali, senza IVA
    _vendita(s, 1, "50", aliquota=_aliquota("N2.2"))               # non soggetta: fuori dai totali
    _acquisto(s, 1, "500")                                         # 110
    _acquisto(s, 1, "100", detraibile=40)                          # 22, detraibile 8,80
    _acquisto(s, 1, "100", nota_credito=True)                      # -22
    _acquisto(s, 2, "999")                                         # altro mese: non entra
    r = calcolo.liquida(s["azienda"], ANNO, "M", 1)
    assert r.attive == D("1100.00") and r.esigibile == D("176.00")
    assert r.passive == D("500.00") and r.detratta == D("96.80") and r.calcolo.indetraibile == D("13.20")
    assert r.iva_dovuta == D("79.20") and r.da_versare == D("79.20") and r.interessi == 0


def test_split_differita_autofatture_e_inversione(s):
    _vendita(s, 3, "1000", aliquota=_aliquota(esigibilita="S"))   # la versa il cliente
    differita = _vendita(s, 3, "1000", aliquota=_aliquota(esigibilita="D"))
    _vendita(s, 3, "100", tipo="TD17")                             # integrazione: 22 a debito e a credito
    _acquisto(s, 3, "100", aliquota="0", natura="N6.7")            # reverse charge: niente nel totale acquisti
    r = calcolo.liquida(s["azienda"], ANNO, "M", 3)
    assert r.esigibile == D("22.00") and r.detratta == D("22.00") and r.passive == 0
    assert r.calcolo.split == D("220.00") and r.calcolo.differita_sospesa == D("220.00")
    scadenza = Scadenza.objects.create(fattura=differita, data=datetime.date(ANNO, 4, 30), importo=differita.totale)
    Incasso.objects.create(scadenza=scadenza, data=datetime.date(ANNO, 4, 20), importo=differita.totale / 2)
    aprile = calcolo.liquida(s["azienda"], ANNO, "M", 4)
    assert aprile.calcolo.differita_incassata == D("110.00") and aprile.esigibile == D("110.00")


def test_riporti_del_credito_e_del_debito_sotto_soglia(s):
    _acquisto(s, 2, "1000")                                        # febbraio: 220 a credito
    _vendita(s, 3, "500")                                          # marzo: 110, meno il credito
    _vendita(s, 4, "1000")                                         # aprile: 220 meno il credito di marzo
    _vendita(s, 5, "200")                                          # maggio: 44, sotto la soglia: rinviato
    _vendita(s, 6, "100")                                          # giugno: 22 + 44
    feb, mar = calcolo.liquida(s["azienda"], ANNO, "M", 2), calcolo.liquida(s["azienda"], ANNO, "M", 3)
    assert feb.a_credito == D("220.00") and mar.credito_precedente == D("220.00") and mar.a_credito == D("110.00")
    apr = calcolo.liquida(s["azienda"], ANNO, "M", 4)
    assert apr.credito_precedente == D("110.00") and apr.da_versare == D("110.00") and not apr.rinviato
    mag, giu = calcolo.liquida(s["azienda"], ANNO, "M", 5), calcolo.liquida(s["azienda"], ANNO, "M", 6)
    assert mag.da_versare == D("44.00") and mag.rinviato and mag.da_versare_ora == 0
    assert giu.debito_precedente == D("44.00") and giu.da_versare == D("66.00")


def test_trimestrale_con_interessi_e_acconto(s):
    parametri.scrivi("iva.periodicita", "T", s["azienda"])
    _vendita(s, 2, "10000")
    t1 = calcolo.liquida(s["azienda"], ANNO, "T", 1)
    assert t1.iva_dovuta == D("2200.00") and t1.interessi == D("22.00") and t1.da_versare == D("2222.00")
    assert t1.scadenza == (datetime.date(ANNO, 5, 16), "6031")
    _vendita(s, 11, "10000")
    Liquidazione.objects.create(azienda=s["azienda"], anno=ANNO, periodicita="T", periodo=4, acconto=D("500"), metodo_acconto=1)
    t4 = calcolo.liquida(s["azienda"], ANNO, "T", 4)
    assert t4.interessi == 0 and t4.da_versare == D("1700.00")


def test_chiusura_congela_e_segnala_le_modifiche(client, superuser, s):
    _vendita(s, 1, "1000")
    url = lambda nome, p: reverse(f"iva:{nome}", args=[ANNO, "M", p])
    client.post(url("chiudi", 2))
    assert not Liquidazione.objects.filter(periodo=2, chiusa=True).exists()        # prima va chiuso gennaio
    client.post(url("chiudi", 1))
    liq = Liquidazione.objects.get(periodo=1)
    assert liq.chiusa and D(liq.dati["da_versare"]) == D("220.00") and liq.chiusa_da == superuser
    _vendita(s, 1, "1000")                                                           # il registro cambia dopo
    r = calcolo.liquida(s["azienda"], ANNO, "M", 1)
    assert r.da_versare == D("220.00") and calcolo.cambiati(r)
    pagina = client.get(url("periodo", 1)).content.decode()
    assert "Dopo la chiusura i registri sono cambiati" in pagina
    client.post(url("versata", 1), {"data": f"{ANNO}-02-16"})
    assert Liquidazione.objects.get(periodo=1).versata_il == datetime.date(ANNO, 2, 16)
    client.post(url("riapri", 1))
    assert calcolo.liquida(s["azienda"], ANNO, "M", 1).da_versare == D("440.00")


def test_voci_manuali_e_pagine(client, superuser, s):
    _vendita(s, 12, "1000")
    risposta = client.post(reverse("iva:periodo", args=[ANNO, "M", 12]),
                           {"credito_anno_precedente": "20", "crediti_imposta": "0", "versamenti_auto": "0", "acconto": "100",
                            "metodo_acconto": "1", "note": ""})
    assert "103,29" in risposta.content.decode()                                     # acconto troppo basso: rifiutato
    client.post(reverse("iva:periodo", args=[ANNO, "M", 12]),
                {"credito_anno_precedente": "20", "crediti_imposta": "0", "versamenti_auto": "0", "acconto": "150",
                 "metodo_acconto": "1", "note": "acconto storico"})
    r = calcolo.liquida(s["azienda"], ANNO, "M", 12)
    assert r.credito_anno_precedente == D("20") and r.da_versare == D("50.00")
    elenco = client.get(reverse("iva:liquidazione") + f"?anno={ANNO}")
    assert elenco.status_code == 200 and "Dicembre" in elenco.content.decode()
    assert b"VP14" in client.get(reverse("iva:liquidazione") + f"?anno={ANNO}&formato=csv").content
    assert client.get(reverse("iva:periodo", args=[ANNO, "X", 1])).status_code == 404


def test_detraibilita_dalla_fattura_ricevuta(client, superuser, s):
    f = _acquisto(s, 1, "100")
    assert "IVA detraibile" in client.get(reverse("sdi:passive_dettaglio", args=[f.pk])).content.decode()
    client.post(reverse("iva:detraibilita", args=[f.pk]), {"percentuale": "50", "motivo": "telefono"})
    assert f.detraibilita.percentuale == 50
    assert calcolo.liquida(s["azienda"], ANNO, "M", 1).detratta == D("11.00")


def test_lipe_mensile(client, superuser, s):
    _vendita(s, 1, "1000")
    _acquisto(s, 2, "2000")
    nome, xml, errori, _ = lipe.genera(s["azienda"], ANNO, 1)
    assert xml is None and any("chi firma" in e for e in errori)                     # società: serve il dichiarante
    parametri.scrivi("iva.cf_dichiarante", "RSSMRA80A01H501U", s["azienda"])
    nome, xml, errori, avvisi = lipe.genera(s["azienda"], ANNO, 1)
    assert not errori and nome == f"LIPE_{s['azienda'].partita_iva}_{ANNO}_T1.xml"
    radice = ET.fromstring(xml)
    assert radice.find("iv:Intestazione/iv:CodiceFornitura", NS).text == "IVP18"
    assert radice.find("iv:Comunicazione/iv:Frontespizio/iv:CFDichiarante", NS).text == "RSSMRA80A01H501U"
    moduli = radice.findall("iv:Comunicazione/iv:DatiContabili/iv:Modulo", NS)
    assert [m.find("iv:Mese", NS).text for m in moduli] == ["1", "2", "3"]
    gennaio, febbraio, marzo = moduli
    assert gennaio.find("iv:IvaEsigibile", NS).text == "220,00" and gennaio.find("iv:ImportoDaVersare", NS).text == "220,00"
    assert febbraio.find("iv:IvaCredito", NS).text == "440,00" and febbraio.find("iv:ImportoACredito", NS).text == "440,00"
    assert marzo.find("iv:CreditoPeriodoPrecedente", NS).text == "440,00"
    ordine = [e.tag.split("}")[1] for e in marzo]
    assert ordine.index("IvaDetratta") < ordine.index("IvaDovuta") < ordine.index("CreditoPeriodoPrecedente") < ordine.index("ImportoACredito")
    assert any("non è chiusa" in a for a in avvisi)
    scaricato = client.get(reverse("iva:lipe") + f"?anno={ANNO}&trimestre=1&scarica=1")
    assert scaricato["Content-Type"] == "application/xml" and scaricato.content == xml
    assert "Scarica il file" in client.get(reverse("iva:lipe") + f"?anno={ANNO}&trimestre=1").content.decode()


def test_lipe_trimestrale_e_partita_iva_sbagliata(s):
    parametri.scrivi("iva.periodicita", "T", s["azienda"])
    parametri.scrivi("iva.cf_dichiarante", "RSSMRA80A01H501U", s["azienda"])
    _vendita(s, 4, "1000")
    _, xml, errori, _ = lipe.genera(s["azienda"], ANNO, 2)
    modulo = ET.fromstring(xml).find("iv:Comunicazione/iv:DatiContabili/iv:Modulo", NS)
    assert modulo.find("iv:Trimestre", NS).text == "2" and modulo.find("iv:InteressiDovuti", NS).text == "2,20"
    assert modulo.find("iv:ImportoDaVersare", NS).text == "222,20"
    s["azienda"].partita_iva = "01234567890"
    s["azienda"].save()
    assert any("partita IVA" in e for e in lipe.genera(s["azienda"], ANNO, 2)[2])


def test_bollo_del_trimestre(s):
    f = _vendita(s, 2, "100", aliquota=_aliquota("N4"))
    Fattura.objects.filter(pk=f.pk).update(bollo=D("2.00"))
    b = calcolo.bollo_trimestre(s["azienda"], ANNO, 1)
    assert b["numero"] == 1 and b["importo"] == D("2.00") and b["codice"] == "2521"
