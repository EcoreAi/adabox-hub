"""Confronto per riga tra fattura del fornitore e ordine: prodotto dal codice articolo del listino o dalla descrizione,
prezzo netto e quantità ricevuta con la tolleranza, blocco facoltativo della registrazione e «Registra comunque»."""
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from acquisti import riscontro
from acquisti.models import VoceListino
from acquisti.tests.test_riscontro import _confermato, _fattura, _ricevi, scena  # noqa: F401
from core import parametri
from sdi import passive
from sdi.models import FatturaPassiva, RigaPassiva


@pytest.fixture
def s(scena):  # noqa: F811
    azienda, fornitore, toner = scena
    VoceListino.objects.create(azienda=azienda, fornitore=fornitore, prodotto=toner, codice_fornitore="TN-100", prezzo=Decimal("10"))
    o = _confermato(azienda, fornitore, toner, quantita=10)
    _ricevi(o, quantita=8)
    f = _fattura(azienda, fornitore, Decimal("100"))
    riscontro.collega(o, f)
    return {"azienda": azienda, "toner": toner, "f": f}


def _riga(f, codice, prezzo, quantita, descrizione="Cartuccia"):
    return RigaPassiva.objects.create(fattura=f, codice_articolo=codice, descrizione=descrizione, quantita=quantita, prezzo=prezzo,
                                      importo=Decimal(prezzo) * Decimal(quantita), aliquota=22)


def test_esiti(s):
    _riga(s["f"], "TN-100", "10.05", "8")                                  # +0,5%: dentro l'1% di tolleranza
    _riga(s["f"], "", "12", "1", descrizione="Toner nero")                 # dalla descrizione, prezzo più alto
    _riga(s["f"], "XX", "5", "1")
    righe = riscontro.confronto_righe(s["f"])
    assert [v["esito"] for v in righe] == ["ok", "prezzo", "sconosciuto"]
    assert righe[0]["prodotto"] == s["toner"] and righe[0]["ricevuto"] == 8 and righe[1]["scarto_prezzo"] == Decimal("20.0")


def test_quantita_oltre_e_blocco(client, s):
    _riga(s["f"], "TN-100", "10", "10")                                    # 10 fatturati, 8 ricevuti
    assert riscontro.problemi(s["f"]) == ["Toner: fatturati 10, ricevuti 8"]
    passive.registra(s["f"])                                               # blocco spento: si registra
    s["f"].stato = FatturaPassiva.DA_VERIFICARE
    s["f"].save()
    parametri.scrivi("acquisti.blocca_registrazione", True, s["azienda"])
    with pytest.raises(ValidationError, match="Fuori tolleranza"):
        passive.registra(s["f"])
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    html = client.get(f"/sdi/passive/{s['f'].pk}/").content.decode()
    assert "Più del ricevuto" in html and "bottone/forza/" in html
    client.post(f"/sdi/passive/{s['f'].pk}/bottone/registra/")
    s["f"].refresh_from_db()
    assert s["f"].stato == FatturaPassiva.DA_VERIFICARE
    client.post(f"/sdi/passive/{s['f'].pk}/bottone/forza/")
    s["f"].refresh_from_db()
    assert s["f"].stato == FatturaPassiva.REGISTRATA


def test_codice_letto_dall_xml():
    xml = b"""<p:FatturaElettronica xmlns:p="x"><FatturaElettronicaHeader><CedentePrestatore><DatiAnagrafici><Anagrafica><Denominazione>A</Denominazione></Anagrafica></DatiAnagrafici></CedentePrestatore><CessionarioCommittente><DatiAnagrafici><Anagrafica><Denominazione>B</Denominazione></Anagrafica></DatiAnagrafici></CessionarioCommittente></FatturaElettronicaHeader>
<FatturaElettronicaBody><DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento><Data>2026-11-01</Data><Numero>1</Numero></DatiGeneraliDocumento></DatiGenerali>
<DatiBeniServizi><DettaglioLinee><NumeroLinea>1</NumeroLinea><CodiceArticolo><CodiceTipo>FORN</CodiceTipo><CodiceValore>TN-100</CodiceValore></CodiceArticolo><Descrizione>Toner</Descrizione><PrezzoUnitario>10</PrezzoUnitario><PrezzoTotale>10</PrezzoTotale><AliquotaIVA>22</AliquotaIVA></DettaglioLinee></DatiBeniServizi></FatturaElettronicaBody></p:FatturaElettronica>"""
    riga, = passive.leggi(xml)["documenti"][0]["righe"]
    assert riga["codice_articolo"] == "TN-100"
