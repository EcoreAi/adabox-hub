"""INV-01: varianti generate dagli attributi, più codici a barre, alternativi, codici dei clienti."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

import fiscale
import prodotti
from contatti.models import Contatto
from core.models import Azienda
from prodotti import varianti
from prodotti.models import (Attributo, AttributoProdotto, CodiceBarre, CodiceCliente, Listino, PrezzoListino, Prodotto,
                             ValoreAttributo, codice_cliente, controlla_unita, da_codice)
from prodotti.prezzi import prezzo


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    taglia = Attributo.objects.create(nome="Taglia", ordine=2)
    colore = Attributo.objects.create(nome="Colore", ordine=1)
    v = {n: ValoreAttributo.objects.create(attributo=taglia, nome=n, ordine=i) for i, n in enumerate(["S", "M", "XL"])}
    v["XL"].sovrapprezzo = Decimal("3")
    v["XL"].save()
    v |= {n: ValoreAttributo.objects.create(attributo=colore, nome=n, codice=c) for n, c in [("Rosso", "RO"), ("Blu", "BL")]}
    maglia = Prodotto.objects.create(azienda=azienda, nome="Maglia", codice="MAG", con_varianti=True,
                                     prezzo_vendita=Decimal("20"), costo=Decimal("8"))
    r = AttributoProdotto.objects.create(prodotto=maglia, attributo=taglia)
    r.valori.set([v["S"], v["M"], v["XL"]])
    r = AttributoProdotto.objects.create(prodotto=maglia, attributo=colore)
    r.valori.set([v["Rosso"], v["Blu"]])
    return {"azienda": azienda, "maglia": maglia, "v": v, "taglia": taglia}


def test_genera_tutte_le_combinazioni(s):
    assert varianti.genera(s["maglia"]) == (6, 0)
    rossa_xl = varianti.per_valori(s["maglia"], [s["v"]["Rosso"], s["v"]["XL"]])
    assert rossa_xl.codice == "MAG-RO-XL" and rossa_xl.nome == "Maglia (Rosso, XL)"
    assert rossa_xl.prezzo_vendita == Decimal("23") and rossa_xl.costo == Decimal("8")
    assert rossa_xl.nome_variante == "Rosso, XL" and "Taglia: XL" in rossa_xl.descrizione_vendita
    assert varianti.genera(s["maglia"]) == (0, 0)                                 # già tutte: niente doppioni


def test_combinazione_tolta_disattiva(s):
    varianti.genera(s["maglia"])
    s["maglia"].attributi.get(attributo=s["taglia"]).valori.remove(s["v"]["XL"])
    assert varianti.genera(s["maglia"]) == (0, 2)
    assert s["maglia"].varianti.filter(attivo=True).count() == 4


def test_senza_attributi_errore(s):
    nuda = Prodotto.objects.create(azienda=s["azienda"], nome="Nuda", con_varianti=True)
    with pytest.raises(ValidationError, match="attributo"):
        varianti.genera(nuda)


def test_modello_non_va_nelle_righe(s):
    riga = type("Riga", (), {"prodotto": s["maglia"], "prodotto_id": s["maglia"].pk, "unita_id": None})()
    with pytest.raises(ValidationError, match="variante"):
        controlla_unita(riga)


def test_campi_comuni_seguono_il_modello(s):
    from fiscale.models import AliquotaIva
    varianti.genera(s["maglia"])
    s["maglia"].aliquota_iva = AliquotaIva.objects.get(codice="10") if AliquotaIva.objects.filter(codice="10").exists() \
        else AliquotaIva.objects.exclude(pk=s["maglia"].aliquota_iva_id).first()
    s["maglia"].attivo = False
    s["maglia"].save()
    assert set(s["maglia"].varianti.values_list("aliquota_iva", "attivo")) == {(s["maglia"].aliquota_iva_id, False)}


def test_validazioni(s):
    altra = Prodotto.objects.create(azienda=s["azienda"], nome="Semplice")
    with pytest.raises(ValidationError, match="con varianti"):
        Prodotto(azienda=s["azienda"], nome="X", variante_di=altra).full_clean()
    with pytest.raises(ValidationError, match="kit"):
        Prodotto(azienda=s["azienda"], nome="Y", con_varianti=True, kit=True).full_clean()


def test_listino_del_modello_vale_per_le_varianti(s):
    varianti.genera(s["maglia"])
    listino = Listino.objects.create(azienda=s["azienda"], nome="Rivenditori")
    PrezzoListino.objects.create(listino=listino, prodotto=s["maglia"], prezzo=Decimal("15"))
    xl = varianti.per_valori(s["maglia"], [s["v"]["Blu"], s["v"]["XL"]])
    s_blu = varianti.per_valori(s["maglia"], [s["v"]["Blu"], s["v"]["S"]])
    assert prezzo(xl, listino) == Decimal("18") and prezzo(s_blu, listino) == Decimal("15")
    PrezzoListino.objects.create(listino=listino, prodotto=xl, prezzo=Decimal("16"))
    assert prezzo(xl, listino) == Decimal("16")                                  # la voce propria vince


def test_sconto_del_modello_vale_per_le_varianti(s):
    from vendite.models import RegolaSconto, sconto_per
    varianti.genera(s["maglia"])
    cliente = Contatto.objects.create(azienda=s["azienda"], nome="Rossi", cliente=True)
    xl = varianti.per_valori(s["maglia"], [s["v"]["Blu"], s["v"]["XL"]])
    RegolaSconto.objects.create(azienda=s["azienda"], nome="Maglie", prodotto=s["maglia"], sconto=Decimal(10))
    assert sconto_per(cliente, xl, 1, datetime.date.today()) == Decimal(10)
    RegolaSconto.objects.create(azienda=s["azienda"], nome="Solo XL blu", prodotto=xl, sconto=Decimal(4))
    assert sconto_per(cliente, xl, 1, datetime.date.today()) == Decimal(4)


def test_codici_a_barre_aggiuntivi(s):
    p = Prodotto.objects.create(azienda=s["azienda"], nome="Penna", codice_barre="111")
    CodiceBarre.objects.create(prodotto=p, codice="8001234567890", nota="EAN produttore")
    assert da_codice(s["azienda"], "8001234567890") == (p, Decimal(1))
    altro = Prodotto.objects.create(azienda=s["azienda"], nome="Matita")
    with pytest.raises(ValidationError, match="Penna"):
        CodiceBarre(prodotto=altro, codice="8001234567890").full_clean()
    with pytest.raises(ValidationError, match="Penna"):
        Prodotto(azienda=s["azienda"], nome="Gomma", codice_barre="8001234567890").full_clean()
    Prodotto(azienda=Azienda.objects.create(nome="Altra"), nome="Gomma", codice_barre="8001234567890").full_clean()


def test_alternativi_nei_due_sensi(s):
    a = Prodotto.objects.create(azienda=s["azienda"], nome="Toner originale")
    b = Prodotto.objects.create(azienda=s["azienda"], nome="Toner compatibile")
    a.alternativi.add(b)
    assert list(b.alternativi.all()) == [a]


def test_codice_cliente(s):
    p = Prodotto.objects.create(azienda=s["azienda"], nome="Vite M6")
    rossi = Contatto.objects.create(azienda=s["azienda"], nome="Rossi", cliente=True)
    CodiceCliente.objects.create(prodotto=p, cliente=rossi, codice="R-778")
    assert codice_cliente(p, rossi).codice == "R-778"
    assert codice_cliente(p, Contatto.objects.create(azienda=s["azienda"], nome="Bianchi")) is None


def test_bottone_e_sezione(client, superuser, s):
    r = client.post(f"/prodotti/prodotti/{s['maglia'].pk}/bottone/genera_varianti/")
    assert r.status_code == 302 and s["maglia"].varianti.count() == 6
    pagina = client.get(f"/prodotti/prodotti/{s['maglia'].pk}/").content.decode()
    assert "Varianti (6)" in pagina and "MAG-RO-XL" in pagina and "Genera varianti" in pagina
    semplice = Prodotto.objects.create(azienda=s["azienda"], nome="Semplice")
    assert "Genera varianti" not in client.get(f"/prodotti/prodotti/{semplice.pk}/").content.decode()
    assert client.get("/prodotti/attributi/").status_code == 200
