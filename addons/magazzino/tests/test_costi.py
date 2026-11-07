"""Costi di magazzino: medio ponderato, FIFO e standard, giacenza negativa, costo dall'ordine d'acquisto, valore a una
data con un movimento retrodatato, ricalcolo dopo il cambio di metodo, pagine ed esportazione."""
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

import fiscale
import prodotti
from contatti.models import Contatto
from core import parametri
from core.models import Azienda
from magazzino import costi, operazioni
from magazzino.models import Consegna, Magazzino, MetodoCosto, Movimento, Ricevimento, RigaConsegna, RigaRicevimento
from prodotti.models import Prodotto

D = Decimal


@pytest.fixture
def s(db):
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    return {"azienda": azienda, "magazzino": Magazzino.predefinito_per(azienda),
            "p": Prodotto.objects.create(azienda=azienda, nome="Monitor", costo=D("90")),
            "cliente": Contatto.objects.create(azienda=azienda, nome="Rossi Srl", cliente=True),
            "fornitore": Contatto.objects.create(azienda=azienda, nome="Grossista Spa", fornitore=True)}


def _mov(s, quantita, costo=None, giorni_fa=0, prodotto=None):
    return Movimento.objects.create(azienda=s["azienda"], prodotto=prodotto or s["p"], magazzino=s["magazzino"],
                                    quantita=D(quantita), costo_unitario=None if costo is None else D(costo),
                                    data=timezone.now() - datetime.timedelta(days=giorni_fa))


def _ricarica(m):
    m.refresh_from_db()
    return m


def test_costo_medio_ponderato(s):
    _mov(s, 10, "100", giorni_fa=3)
    _mov(s, 10, "120", giorni_fa=2)
    uscita = _ricarica(_mov(s, -5, giorni_fa=1))
    assert uscita.costo_unitario == D("110.0000") and uscita.valore == D("-550.00")
    stato, _ = costi.ripercorri(s["p"])
    assert stato.quantita == 15 and costi.q2(stato.valore) == D("1650.00") and stato.costo_corrente == D("110.0000")


def test_fifo_e_cambio_di_metodo(s):
    _mov(s, 10, "100", giorni_fa=3)
    _mov(s, 10, "120", giorni_fa=2)
    uscita = _mov(s, -15, giorni_fa=1)
    assert _ricarica(uscita).costo_unitario == D("110.0000")                     # medio ponderato
    MetodoCosto.objects.create(prodotto=s["p"], metodo=costi.FIFO)
    s["p"].refresh_from_db()
    assert costi.ricalcola(s["p"]) == 1
    uscita.refresh_from_db()
    assert uscita.costo_unitario == D("106.6667")                                # 10 a 100 + 5 a 120
    stato, _ = costi.ripercorri(s["p"])
    assert stato.costo_corrente == D("120.0000") and costi.q2(stato.valore) == D("600.00")


def test_standard_dalla_scheda_del_prodotto(s):
    parametri.scrivi("magazzino.metodo_costo", "standard", s["azienda"])
    _mov(s, 4, "100")
    assert _ricarica(_mov(s, -1)).costo_unitario == D("90.0000")
    assert costi.valorizzazione([s["p"]])[0]["valore"] == D("270.00")


@pytest.mark.parametrize("metodo", [costi.MEDIO, costi.FIFO])
def test_giacenza_negativa_poi_carico(s, metodo):
    parametri.scrivi("magazzino.metodo_costo", metodo, s["azienda"])
    _mov(s, 2, "50", giorni_fa=3)
    negativa = _ricarica(_mov(s, -5, giorni_fa=2))
    assert negativa.costo_unitario == D("50.0000")
    _mov(s, 10, "80", giorni_fa=1)
    stato, _ = costi.ripercorri(s["p"])
    assert stato.quantita == 7 and stato.costo_corrente == D("80.0000") and costi.q2(stato.valore) == D("560.00")


def test_valore_a_una_data_con_movimento_retrodatato(s):
    _mov(s, 10, "100", giorni_fa=10)
    uscita = _mov(s, -4, giorni_fa=2)
    assert _ricarica(uscita).costo_unitario == D("100.0000")
    _mov(s, 10, "200", giorni_fa=5)                                              # inserito dopo, con data passata
    assert _ricarica(uscita).costo_unitario == D("150.0000")                     # ricalcolato in ordine di data
    otto_giorni_fa = timezone.now() - datetime.timedelta(days=8)
    assert costi.valorizzazione([s["p"]], otto_giorni_fa)[0]["valore"] == D("1000.00")
    oggi = costi.valorizzazione([s["p"]])[0]
    assert oggi["quantita"] == 16 and oggi["valore"] == D("2400.00")


def test_rettifica_senza_costo_prende_quello_attuale(s):
    _mov(s, 10, "100")
    rettifica = _ricarica(_mov(s, 2))
    assert rettifica.costo_unitario == D("100.0000") and not rettifica.costo_fissato
    con_costo = _ricarica(_mov(s, 1, "40"))
    assert con_costo.costo_fissato and con_costo.costo_unitario == D("40.0000")


def test_ricevimento_al_prezzo_dell_ordine(s):
    from django.contrib.contenttypes.models import ContentType

    from acquisti.models import OrdineAcquisto, RigaAcquisto
    ordine = OrdineAcquisto.objects.create(azienda=s["azienda"], fornitore=s["fornitore"])
    RigaAcquisto.objects.create(ordine=ordine, prodotto=s["p"], quantita=10, prezzo=D("100"), sconto=D("10"))
    ricevimento = Ricevimento.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], fornitore=s["fornitore"],
                                             origine_tipo=ContentType.objects.get_for_model(ordine), origine_id=ordine.pk)
    RigaRicevimento.objects.create(ricevimento=ricevimento, prodotto=s["p"], quantita=10)
    altro = Prodotto.objects.create(azienda=s["azienda"], nome="Cavo", costo=D("3"))
    RigaRicevimento.objects.create(ricevimento=ricevimento, prodotto=altro, quantita=5, costo=D("2.5"))
    operazioni.ricevi(ricevimento)
    m = Movimento.objects.get(prodotto=s["p"])
    assert m.costo_unitario == D("90.0000") and m.costo_fissato and m.valore == D("900.00")
    assert Movimento.objects.get(prodotto=altro).costo_unitario == D("2.5000")
    consegna = Consegna.objects.create(azienda=s["azienda"], magazzino=s["magazzino"], cliente=s["cliente"])
    RigaConsegna.objects.create(consegna=consegna, prodotto=s["p"], quantita=3)
    operazioni.spedisci(consegna)
    assert Movimento.objects.get(prodotto=s["p"], quantita__lt=0).valore == D("-270.00")


def test_pagine_e_pacchetto(client, superuser, s):
    _mov(s, 10, "100", giorni_fa=3)
    lista = client.get(reverse("magazzino:movimenti_lista")).content.decode()
    assert "1.000,00" in lista and "Valore" in lista
    pagina = client.get(reverse("magazzino:valore")).content.decode()
    assert "Monitor" in pagina and "1.000,00" in pagina
    csv = client.get(reverse("magazzino:valore") + "?formato=csv").content.decode("utf-8-sig")
    assert "Monitor" in csv and "1000,00" in csv
    assert "Costo di magazzino" in client.get(reverse("prodotti:prodotti_dettaglio", args=[s["p"].pk])).content.decode()
    client.post(reverse("magazzino:metodo_prodotto", args=[s["p"].pk]), {"metodo": "fifo"})
    assert MetodoCosto.objects.get(prodotto=s["p"]).metodo == "fifo"
    Movimento.objects.filter(prodotto=s["p"]).update(valore=None)
    client.post(reverse("magazzino:ricalcola"))
    assert Movimento.objects.get(prodotto=s["p"]).valore == D("1000.00")
    rettifica = client.post(reverse("magazzino:movimenti_nuovo"), {"prodotto": s["p"].pk, "magazzino": s["magazzino"].pk,
                                                                      "quantita": "-1", "costo_unitario": "5", "causale": "x"})
    assert "solo per i carichi" in rettifica.content.decode()
    from magazzino.per_commercialista import inventario

    class R:
        user, azienda = superuser, s["azienda"]
    file = list(inventario(R, timezone.localdate().year, None, []))
    assert file and "Monitor" in file[0][1].decode("utf-8-sig")
