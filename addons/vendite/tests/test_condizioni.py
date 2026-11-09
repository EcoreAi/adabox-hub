"""Condizioni di vendita: listino del cliente sugli ordini nuovi, voci di listino con date di validità, regole di sconto
per cliente, prodotto, categoria e quantità (vince la più precisa), sconto generale, pagina sulla scheda."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from prodotti.models import Categoria, Listino, PrezzoListino, Prodotto
from vendite.models import CondizioniCliente, OrdineVendita, RegolaSconto, RigaVendita

OGGI = datetime.date.today()


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    hw = Categoria.objects.create(nome="Hardware")
    monitor = Prodotto.objects.create(azienda=azienda, nome="Monitor", prezzo_vendita=Decimal("200"), categoria=hw)
    cavo = Prodotto.objects.create(azienda=azienda, nome="Cavo", prezzo_vendita=Decimal("10"))
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi", cliente=True)
    rivenditori = Listino.objects.create(azienda=azienda, nome="Rivenditori")
    PrezzoListino.objects.create(listino=rivenditori, prodotto=monitor, prezzo=Decimal("180"))
    PrezzoListino.objects.create(listino=rivenditori, prodotto=monitor, prezzo=Decimal("150"), valido_dal=OGGI - datetime.timedelta(days=30),
                                 valido_al=OGGI - datetime.timedelta(days=1))          # promozione finita
    return {"azienda": azienda, "monitor": monitor, "cavo": cavo, "rossi": rossi, "listino": rivenditori, "hw": hw}


def _riga(s, prodotto, quantita=1):
    o = OrdineVendita.objects.create(azienda=s["azienda"], cliente=s["rossi"])
    return o, RigaVendita.objects.create(ordine=o, prodotto=prodotto, quantita=quantita)


def test_listino_del_cliente_e_validita(s):
    CondizioniCliente.objects.create(azienda=s["azienda"], contatto=s["rossi"], listino=s["listino"])
    o, r = _riga(s, s["monitor"])
    assert o.listino == s["listino"] and r.prezzo == Decimal("180")              # la voce scaduta non conta
    _, r = _riga(s, s["cavo"])
    assert r.prezzo == Decimal("10")                                             # non in listino: prezzo del prodotto


def test_regole_di_sconto(s):
    RegolaSconto.objects.create(azienda=s["azienda"], nome="Tutti, hardware", categoria=s["hw"], sconto=Decimal(5))
    RegolaSconto.objects.create(azienda=s["azienda"], nome="Rossi, monitor da 10", cliente=s["rossi"], prodotto=s["monitor"],
                                quantita_minima=10, sconto=Decimal(12))
    CondizioniCliente.objects.create(azienda=s["azienda"], contatto=s["rossi"], sconto=Decimal(2))
    assert _riga(s, s["monitor"], 1)[1].sconto == Decimal(5)
    assert _riga(s, s["monitor"], 10)[1].sconto == Decimal(12)
    assert _riga(s, s["cavo"], 1)[1].sconto == Decimal(2)                        # nessuna regola: lo sconto generale
    o = OrdineVendita.objects.create(azienda=s["azienda"], cliente=s["rossi"])
    scelta = RigaVendita.objects.create(ordine=o, prodotto=s["monitor"], quantita=1, sconto=Decimal(1))
    assert scelta.sconto == Decimal(1)                                           # scelto a mano: resta
    RegolaSconto.objects.create(azienda=s["azienda"], nome="Scaduta", prodotto=s["cavo"], sconto=Decimal(50), al=OGGI - datetime.timedelta(days=1))
    assert _riga(s, s["cavo"], 1)[1].sconto == Decimal(2)


def test_pagina_sulla_scheda(client, s):
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    assert "Listino e sconto" in client.get(f"/contatti/contatti/{s['rossi'].pk}/").content.decode()
    client.post(f"/vendite/contatto/{s['rossi'].pk}/condizioni/", {"listino": s["listino"].pk, "sconto": "3,5"})
    c = CondizioniCliente.objects.get()
    assert c.listino == s["listino"] and c.sconto == Decimal("3.5")
    assert client.get("/vendite/sconti/").status_code == 200
