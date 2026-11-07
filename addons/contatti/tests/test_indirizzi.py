"""Indirizzi del contatto (consegna, fatturazione, sedi): predefinito per tipo, solo dello stesso cliente su ordine e
consegna, riporto dall'ordine alla consegna e sul DDT; società madre tra aziende senza giri."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

import fiscale
import prodotti
from contatti.models import Contatto, IndirizzoContatto
from core.models import Azienda
from magazzino import collegamenti
from magazzino.models import Consegna
from prodotti.models import Prodotto
from vendite.models import OrdineVendita, RigaVendita


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    rossi = Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True, indirizzo="Via Roma 1", citta="Milano")
    return {"azienda": azienda, "rossi": rossi,
            "bari": IndirizzoContatto.objects.create(contatto=rossi, nome="Magazzino di Bari", indirizzo="Via Napoli 4",
                                                     cap="70100", citta="Bari", provincia="ba", predefinito=True)}


def test_predefinito_per_tipo(s):
    assert s["bari"].azienda == s["azienda"] and IndirizzoContatto.predefinito_per(s["rossi"], "consegna") == s["bari"]
    lecce = IndirizzoContatto.objects.create(contatto=s["rossi"], indirizzo="Via Lecce 2", citta="Lecce", predefinito=True)
    s["bari"].refresh_from_db()
    assert not s["bari"].predefinito and IndirizzoContatto.predefinito_per(s["rossi"], "consegna") == lecce
    s["bari"].full_clean()
    assert s["bari"].provincia == "BA" and s["bari"].righe == ["Magazzino di Bari", "Via Napoli 4", "70100 Bari (BA)"]


def test_indirizzo_di_un_altro_cliente(s):
    verdi = Contatto.objects.create(azienda=s["azienda"], nome="Verdi Spa", cliente=True)
    ordine = OrdineVendita(azienda=s["azienda"], cliente=verdi, indirizzo_consegna=s["bari"])
    with pytest.raises(ValidationError, match="altro contatto"):
        ordine.full_clean()
    with pytest.raises(ValidationError, match="altro contatto"):
        Consegna(azienda=s["azienda"], cliente=verdi, destinazione=s["bari"], magazzino_id=1).clean()


def test_dall_ordine_alla_consegna_e_al_ddt(client, superuser, s):
    monitor = Prodotto.objects.create(azienda=s["azienda"], nome="Monitor", prezzo_vendita=Decimal("200"))
    ordine = OrdineVendita.objects.create(azienda=s["azienda"], cliente=s["rossi"])
    RigaVendita.objects.create(ordine=ordine, prodotto=monitor, quantita=2)
    consegna = collegamenti.consegna_da_ordine(OrdineVendita, ordine)
    assert consegna.destinazione == s["bari"]                                       # il predefinito del cliente
    sede = IndirizzoContatto.objects.create(contatto=s["rossi"], tipo="sede", indirizzo="Via Po 9", citta="Torino")
    ordine.indirizzo_consegna = sede
    ordine.save()
    assert collegamenti.consegna_da_ordine(OrdineVendita, ordine).destinazione == sede   # quello scelto sull'ordine
    ddt = client.get(reverse("magazzino:consegne_dettaglio", args=[consegna.pk]))
    assert ddt.status_code == 200
    from django.template.loader import render_to_string
    from django.test import RequestFactory
    richiesta = RequestFactory().get("/")
    richiesta.user, richiesta.azienda = superuser, s["azienda"]
    html = render_to_string("magazzino/report/ddt.html", {"obj": consegna, "oggetti": [consegna]}, request=richiesta)
    assert "Magazzino di Bari" in html and "70100 Bari (BA)" in html and "Luogo di destinazione" in html


def test_scheda_del_contatto_e_societa_madre(client, superuser, s):
    pagina = client.get(reverse("contatti:contatti_dettaglio", args=[s["rossi"].pk])).content.decode()
    assert "Altri indirizzi (1)" in pagina and "Magazzino di Bari" in pagina and "Aggiungi indirizzo" in pagina
    client.post(reverse("contatti:indirizzi_nuovo"), {"contatto": s["rossi"].pk, "tipo": "fatturazione", "indirizzo": "Via Verdi 3",
                                                       "citta": "Roma", "nazione": "IT"})
    assert IndirizzoContatto.objects.filter(tipo="fatturazione", azienda=s["azienda"]).exists()
    gruppo = Contatto.objects.create(azienda=s["azienda"], nome="Gruppo Rossi Holding")
    s["rossi"].societa = gruppo
    s["rossi"].full_clean()
    s["rossi"].save()
    gruppo.societa = s["rossi"]
    with pytest.raises(ValidationError, match="appartiene già"):
        gruppo.full_clean()
