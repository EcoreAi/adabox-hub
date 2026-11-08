"""AI-03: le proposte imparano dagli abbinamenti confermati (IBAN, controparte, causale ricorrente) e dicono perché;
quello imparato non basta mai per abbinare da solo."""
from decimal import Decimal as D

from banca import abbina, memoria
from banca.models import MovimentoBanca
from banca.tests.test_banca import G, _fattura, _mov, s  # noqa: F401  (fixture)
from contatti.models import Contatto
from sdi.models import FatturaPassiva, ScadenzaPassiva


def _passiva(s, importo, numero):
    f = FatturaPassiva.objects.create(azienda=s["az"], fornitore=s["fornitore"], numero=numero, data=G(2026, 1, 1),
                                      totale=D(importo), nome_file=f"{numero}.xml")
    return ScadenzaPassiva.objects.create(fattura=f, data=G(2026, 6, 30), importo=D(importo))

IBAN_ROSSI = "IT02L1234512345123456789012"


def _con_iban(mov, iban=IBAN_ROSSI):
    MovimentoBanca.objects.filter(pk=mov.pk).update(iban_controparte=iban)
    return MovimentoBanca.objects.get(pk=mov.pk)


def test_impara_dall_iban_di_chi_ha_gia_pagato(s):
    bianchi = Contatto.objects.create(azienda=s["az"], nome="Bianchi Spa", cliente=True, partita_iva="01114601006")
    vecchia = _fattura(s, 100)
    primo = _con_iban(_mov(s, "122.00", "Bonifico", data=G(2026, 5, 10)))
    abbina.abbina(primo, [f"a{vecchia.scadenze.get().pk}"], s["io"])               # confermato da una persona
    aperta_rossi, aperta_bianchi = _fattura(s, 500), _fattura(s, 500, bianchi)
    nuovo = _con_iban(_mov(s, "300.00", "Acconto lavori"))                          # né numero né importo
    attive, passive = abbina.aperte_attive(s["az"]), abbina.aperte_passive(s["az"])
    assert abbina.proposte(nuovo, attive, passive) == []                            # senza memoria: niente
    lista = abbina.proposte(nuovo, attive, passive, storia=memoria.di(s["az"]))
    assert [p.documento for p in lista] == [aperta_rossi] and aperta_bianchi not in [p.documento for p in lista]
    assert "Dallo stesso IBAN già 1 volta" in lista[0].motivi


def test_causale_ricorrente_del_fornitore(s):
    for mese in (3, 4):
        sp = _passiva(s, 80, f"E{mese}")
        m = _mov(s, "-80.00", f"SDD ENEL ENERGIA {mese:02d}/2026 ADDEBITO", data=G(2026, mese, 28))
        abbina.abbina(m, [f"p{sp.pk}"], s["io"])
    nuova = _passiva(s, 95, "E6")
    m = _mov(s, "-95.00", "SDD ENEL ENERGIA 06/2026 ADDEBITO")
    storia = memoria.di(s["az"])
    (p,) = abbina.proposte(m, [], abbina.aperte_passive(s["az"]), storia=storia)
    assert p.scadenza == nuova and "Causale ricorrente, già abbinata 2 volte" in p.motivi and p.punti == 30 + 20
    assert memoria.firma_causale("SDD ENEL ENERGIA 06/2026 ADDEBITO") == memoria.firma_causale("sdd enel energia 07-2026 addebito")


def test_la_storia_non_fa_abbinare_da_sola(s):
    vecchia = _fattura(s, 100)
    primo = _con_iban(_mov(s, "122.00", "Bonifico 12345678903", data=G(2026, 5, 10)))
    abbina.abbina(primo, [f"a{vecchia.scadenze.get().pk}"], s["io"])
    aperta = _fattura(s, 200)
    nuovo = _con_iban(_mov(s, "244.00", "Bonifico 12345678903"))                    # P.IVA + importo + IBAN, senza numero
    lista = abbina.proposte(nuovo, abbina.aperte_attive(s["az"]), [], storia=memoria.di(s["az"]))
    assert lista[0].documento == aperta and lista[0].punti >= abbina.SICURO          # tanti punti…
    assert not abbina.e_sicura(lista)                                                # …ma non «sicura»
    assert abbina.abbina_i_sicuri(s["az"], s["io"]) == 0


def test_la_pagina_dice_perche(s, client):
    vecchia = _fattura(s, 100)
    primo = _con_iban(_mov(s, "122.00", "Bonifico", data=G(2026, 5, 10)))
    abbina.abbina(primo, [f"a{vecchia.scadenze.get().pk}"], s["io"])
    _fattura(s, 500)
    _con_iban(_mov(s, "300.00", "Acconto"))
    client.force_login(s["io"])
    assert "Dallo stesso IBAN già 1 volta" in client.get("/banca/riconcilia/").content.decode()
