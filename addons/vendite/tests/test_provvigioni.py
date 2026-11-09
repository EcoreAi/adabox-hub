"""Provvigioni: piano del commerciale, regole per prodotto e categoria, maturazione alla conferma o all'incasso,
annullamento, estratto con la maggiorazione a obiettivo raggiunto, liquidazione."""
import datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from fatturazione import operazioni as fatture
from fatturazione.models import DatiFiscali, Fattura, Incasso
from fiscale.models import AliquotaIva
from prodotti.models import Categoria, Prodotto
from vendite import operazioni, provvigioni
from vendite.models import OrdineVendita, PianoProvvigioni, Provvigione, RegolaProvvigione, RigaVendita
from vendite.segnali import ordine_annullato, ordine_confermato

OGGI = datetime.date.today()


@pytest.fixture
def s(db, client):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    azienda.partita_iva, azienda.indirizzo, azienda.cap, azienda.citta, azienda.provincia = (
        "01234567897", "Via Roma 1", "00100", "Roma", "RM")
    azienda.save()
    DatiFiscali.objects.create(azienda=azienda, iban="IT60X0542811101000000123456", banca="Banca")
    cliente = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, email="rossi@example.com",
                                      partita_iva="12345678903", codice_sdi="ABC1234", indirizzo="Via Po 2", cap="20100",
                                      citta="Milano", provincia="MI")
    lia = User.objects.create_user("lia", "lia@example.com", "x")
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    client.force_login(root)
    return {"azienda": azienda, "cliente": cliente, "lia": lia, "root": root}


def _piano(s, percentuale="5", **extra):
    return PianoProvvigioni.objects.create(azienda=s["azienda"], nome="Base", percentuale=D(percentuale), **extra)


def _ordine(s, righe=(("Lavoro", "1000", None),), commerciale="lia", numero="PV/1"):
    o = OrdineVendita.objects.create(azienda=s["azienda"], cliente=s["cliente"], numero=numero,
                                     commerciale=s[commerciale] if commerciale else None)
    for descrizione, prezzo, prodotto in righe:
        RigaVendita.objects.create(ordine=o, descrizione=descrizione, prezzo=D(prezzo), prodotto=prodotto,
                                   aliquota=AliquotaIva.objects.get(codice="22"))
    o.ricalcola()
    return o


# ---------- quale piano e quale percentuale

def test_piano_proprio_prima_di_quello_generale_e_solo_se_valido(s):
    generale = _piano(s)
    assert provvigioni.piano_per(s["lia"], s["azienda"].pk, OGGI) == generale
    proprio = _piano(s, "8", utente=s["lia"])
    assert provvigioni.piano_per(s["lia"], s["azienda"].pk, OGGI) == proprio
    proprio.dal = OGGI + datetime.timedelta(days=1)                        # non ancora valido: torna il generale
    proprio.save()
    assert provvigioni.piano_per(s["lia"], s["azienda"].pk, OGGI) == generale
    generale.attivo = False
    generale.save()
    assert provvigioni.piano_per(s["lia"], s["azienda"].pk, OGGI) is None
    assert provvigioni.piano_per(None, s["azienda"].pk, OGGI) is None     # ordine senza commerciale


def test_regola_del_prodotto_poi_della_categoria_poi_la_base(s):
    hardware = Categoria.objects.create(nome="Hardware")
    monitor = Prodotto.objects.create(azienda=s["azienda"], nome="Monitor", categoria=hardware, prezzo_vendita=D("100"))
    mouse = Prodotto.objects.create(azienda=s["azienda"], nome="Mouse", categoria=hardware, prezzo_vendita=D("100"))
    piano = _piano(s)
    RegolaProvvigione.objects.create(piano=piano, categoria=hardware, percentuale=D("3"))
    RegolaProvvigione.objects.create(piano=piano, prodotto=monitor, percentuale=D("10"))
    o = _ordine(s, [("Monitor", "1000", monitor), ("Mouse", "1000", mouse), ("Consulenza", "1000", None)])
    assert provvigioni.calcola(o, piano) == (D("3000.00"), D("180.00"))   # 100 + 30 + 50


# ---------- maturazione alla conferma

def test_matura_alla_conferma_una_volta_sola(s):
    _piano(s)
    o = _ordine(s)
    operazioni.conferma(o)
    p = Provvigione.objects.get()
    assert (p.utente, p.ordine, p.base, p.importo, p.stato) == (s["lia"], o, D("1000.00"), D("50.00"), Provvigione.MATURATA)
    ordine_confermato.send(sender=OrdineVendita, ordine=o, utente=None)    # una seconda conferma non la raddoppia
    assert Provvigione.objects.count() == 1


def test_senza_piano_o_senza_commerciale_nessuna_provvigione(s):
    operazioni.conferma(_ordine(s))
    _piano(s)
    operazioni.conferma(_ordine(s, commerciale=None, numero="PV/2"))
    assert not Provvigione.objects.exists()


def test_annullamento_annulla_le_maturate_non_le_liquidate(s):
    _piano(s)
    o1, o2 = _ordine(s), _ordine(s, numero="PV/2")
    operazioni.conferma(o1)
    operazioni.conferma(o2)
    provvigioni.liquida(s["lia"], s["azienda"].pk, OGGI, OGGI)
    Provvigione.objects.filter(ordine=o2).update(stato=Provvigione.MATURATA, liquidata_il=None)
    risposte = ordine_annullato.send(sender=OrdineVendita, ordine=o2, utente=None)
    assert Provvigione.objects.get(ordine=o2).stato == Provvigione.ANNULLATA
    assert "Annullate 1 provvigioni." in [testo for _, testo in risposte]
    ordine_annullato.send(sender=OrdineVendita, ordine=o1, utente=None)
    assert Provvigione.objects.get(ordine=o1).stato == Provvigione.LIQUIDATA


# ---------- maturazione all'incasso

def test_all_incasso_matura_in_proporzione_agli_incassi(s):
    _piano(s, maturazione=PianoProvvigioni.INCASSO)
    o = _ordine(s)
    operazioni.conferma(o)
    assert not Provvigione.objects.exists()                               # alla conferma ancora niente
    fattura = fatture.da_ordine(o)
    fatture.emetti(fattura)
    fatture.incassa_fattura(Fattura.objects.get(pk=fattura.pk), D("610"))  # metà dei 1220 IVA compresa
    p = Provvigione.objects.get()
    assert (p.base, p.importo, p.incasso_id) == (D("500.00"), D("25.00"), Incasso.objects.get().pk)
    fatture.incassa_fattura(Fattura.objects.get(pk=fattura.pk), D("610"))
    assert sorted(Provvigione.objects.values_list("importo", flat=True)) == [D("25.00"), D("25.00")]


def test_incasso_eliminato_annulla_la_sua_provvigione(s):
    _piano(s, maturazione=PianoProvvigioni.INCASSO)
    o = _ordine(s)
    operazioni.conferma(o)
    fattura = fatture.da_ordine(o)
    fatture.emetti(fattura)
    fatture.incassa_fattura(Fattura.objects.get(pk=fattura.pk), D("1220"))
    Incasso.objects.get().delete()
    assert Provvigione.objects.get().stato == Provvigione.ANNULLATA


def test_piano_alla_conferma_ignora_gli_incassi(s):
    _piano(s)
    o = _ordine(s)
    operazioni.conferma(o)
    fattura = fatture.da_ordine(o)
    fatture.emetti(fattura)
    fatture.incassa_fattura(Fattura.objects.get(pk=fattura.pk), D("1220"))
    assert Provvigione.objects.count() == 1                               # solo quella della conferma


# ---------- estratto e liquidazione

def test_estratto_con_maggiorazione_a_obiettivo_raggiunto(s):
    from crm.models import ObiettivoVendita
    _piano(s, maggiorazione=D("2"))
    operazioni.conferma(_ordine(s))
    e = provvigioni.estratto(s["lia"], s["azienda"].pk, OGGI, OGGI)
    assert (e["totale"], e["obiettivo"], e["maggiorazione"], e["da_pagare"]) == (D("50.00"), None, D(0), D("50.00"))
    ObiettivoVendita.objects.create(azienda=s["azienda"], utente=s["lia"], dal=OGGI, al=OGGI, importo=D("2000"))
    e = provvigioni.estratto(s["lia"], s["azienda"].pk, OGGI, OGGI)
    assert not e["raggiunto"] and e["percentuale_obiettivo"] == 50 and e["maggiorazione"] == D(0)
    ObiettivoVendita.objects.filter(utente=s["lia"]).update(importo=D("800"))
    e = provvigioni.estratto(s["lia"], s["azienda"].pk, OGGI, OGGI)
    assert e["raggiunto"] and e["maggiorazione"] == D("20.00") and e["da_pagare"] == D("70.00")   # +2% su 1000


def test_liquida_solo_le_maturate_del_periodo(s):
    _piano(s)
    operazioni.conferma(_ordine(s))
    operazioni.conferma(_ordine(s, numero="PV/2"))
    Provvigione.objects.filter(ordine__numero="PV/2").update(data=OGGI - datetime.timedelta(days=40))
    assert provvigioni.liquida(s["lia"], s["azienda"].pk, OGGI, OGGI) == 1
    assert provvigioni.estratto(s["lia"], s["azienda"].pk, OGGI, OGGI)["da_liquidare"] == D(0)
    assert Provvigione.objects.get(ordine__numero="PV/2").stato == Provvigione.MATURATA


# ---------- pagine

def test_pagine_e_liquidazione_dall_estratto(client, s):
    _piano(s)
    operazioni.conferma(_ordine(s))
    for url in ("/vendite/provvigioni/", "/vendite/piani-provvigioni/", "/vendite/provvigioni/estratto/"):
        assert client.get(url).status_code == 200, url
    html = client.get(f"/vendite/provvigioni/estratto/?utente={s['lia'].pk}").content.decode()
    assert "50,00" in html
    r = client.post("/vendite/provvigioni/estratto/", {"utente": s["lia"].pk, "dal": OGGI.isoformat(), "al": OGGI.isoformat(),
                                                       "azione": "liquida"})
    assert r.status_code == 302 and Provvigione.objects.get().stato == Provvigione.LIQUIDATA


def test_il_commerciale_vede_solo_le_sue(client, s):
    _piano(s)
    operazioni.conferma(_ordine(s))
    operazioni.conferma(_ordine(s, commerciale="root", numero="PV/2"))
    s["lia"].user_permissions.add(Permission.objects.get(codename="view_provvigione"))
    s["lia"].profilo.aziende.set([s["azienda"]])
    client.force_login(s["lia"])
    righe = client.get("/vendite/provvigioni/").context["page_obj"]
    assert [p.utente for p in righe] == [s["lia"]]
    estratto = client.get(f"/vendite/provvigioni/estratto/?utente={s['root'].pk}")
    assert estratto.context["scelto"] == s["lia"]                          # non può guardare quello degli altri
    client.post("/vendite/provvigioni/estratto/", {"utente": s["lia"].pk, "dal": OGGI.isoformat(), "al": OGGI.isoformat(),
                                                   "azione": "liquida"})
    assert not Provvigione.objects.filter(stato=Provvigione.LIQUIDATA).exists()   # liquidare spetta a chi gestisce


def test_incasso_corretto_ricalcola_la_provvigione_da_liquidare(s):
    _piano(s, maturazione=PianoProvvigioni.INCASSO)
    o = _ordine(s)
    operazioni.conferma(o)
    fattura = fatture.da_ordine(o)
    fatture.emetti(fattura)
    fatture.incassa_fattura(Fattura.objects.get(pk=fattura.pk), D("610"))
    incasso = Incasso.objects.get()
    incasso.importo = D("1220")                                            # registrato male: era tutto
    incasso.save()
    p = Provvigione.objects.get()                                          # la stessa, ricalcolata
    assert (p.base, p.importo, p.stato) == (D("1000.00"), D("50.00"), Provvigione.MATURATA)
    incasso.importo = D("0")
    incasso.save()
    assert Provvigione.objects.get().stato == Provvigione.ANNULLATA


def test_incasso_corretto_dopo_la_liquidazione_non_la_cambia(s):
    _piano(s, maturazione=PianoProvvigioni.INCASSO)
    o = _ordine(s)
    operazioni.conferma(o)
    fattura = fatture.da_ordine(o)
    fatture.emetti(fattura)
    fatture.incassa_fattura(Fattura.objects.get(pk=fattura.pk), D("610"))
    provvigioni.liquida(s["lia"], s["azienda"].pk, OGGI, OGGI)
    incasso = Incasso.objects.get()
    incasso.importo = D("1220")
    incasso.save()
    p = Provvigione.objects.get()
    assert (p.importo, p.stato) == (D("25.00"), Provvigione.LIQUIDATA)
