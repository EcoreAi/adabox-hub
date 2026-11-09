"""Segmenti e classe ABC: ABC dal fatturato dei 12 mesi (note di credito in meno), regole del segmento, aggiunti ed
esclusi, ricalcolo al salvataggio, filtro della lista, condizione delle automazioni."""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from contatti import segmenti
from contatti.models import Contatto, Segmento
from core.models import Azienda

OGGI = timezone.localdate()


@pytest.fixture
def s(db):
    from fatturazione.models import Fattura
    azienda = Azienda.objects.get(pk=1)
    c = {n: Contatto.objects.create(azienda=azienda, nome=n, cliente=True, provincia=p)
         for n, p in [("Grande", "MI"), ("Medio", "MI"), ("Piccolo", "RM"), ("Dormiente", "RM"), ("Mai", "TO")]}
    Contatto.objects.create(azienda=azienda, nome="Fornitore", fornitore=True)

    def fattura(cliente, imponibile, giorni=10, tipo=Fattura.FATTURA):
        f = Fattura.objects.create(azienda=azienda, cliente=c[cliente], tipo=tipo, data=OGGI - datetime.timedelta(days=giorni))
        Fattura.objects.filter(pk=f.pk).update(stato=Fattura.EMESSA, imponibile=Decimal(imponibile))
    fattura("Grande", 9000)
    fattura("Grande", 1000, tipo=Fattura.NOTA_CREDITO)        # netto 8000
    fattura("Medio", 1500, giorni=100)
    fattura("Piccolo", 500)
    fattura("Dormiente", 400, giorni=300)
    fattura("Dormiente", 99999, giorni=500)                  # fuori dai 12 mesi
    return azienda, c


def test_classi_abc(s):
    azienda, c = s
    assert segmenti.classi_abc(azienda.pk) == {"A": 2, "B": 1, "C": 1}     # Medio parte dal 77% della cumulata
    valori = {x.nome: (x.classe_abc, x.fatturato_12_mesi) for x in Contatto.objects.filter(azienda=azienda)}
    assert valori["Grande"] == ("A", Decimal("8000.00")) and valori["Medio"][0] == "A"
    assert valori["Piccolo"][0] == "B" and valori["Dormiente"] == ("C", Decimal("400.00")) and valori["Mai"] == ("", 0)


def test_regole_aggiunti_ed_esclusi(s):
    azienda, c = s
    segmenti.classi_abc(azienda.pk)
    milano = Segmento.objects.create(azienda=azienda, nome="Milano", province="mi, mb")
    assert segmenti.ricalcola_segmento(milano) == 2
    top = Segmento.objects.create(azienda=azienda, nome="Top", classi="AB", fatturato_minimo=Decimal("1000"))
    segmenti.ricalcola_segmento(top)
    assert set(top.membri.values_list("nome", flat=True)) == {"Grande", "Medio"}
    dormienti = Segmento.objects.create(azienda=azienda, nome="Dormienti", inattivo_da=200)
    segmenti.ricalcola_segmento(dormienti)
    assert list(dormienti.membri.values_list("nome", flat=True)) == ["Dormiente"]
    recenti = Segmento.objects.create(azienda=azienda, nome="Recenti", acquisto_entro=30)
    recenti.aggiunti.add(c["Mai"])
    recenti.esclusi.add(c["Piccolo"])
    segmenti.ricalcola_segmento(recenti)
    assert set(recenti.membri.values_list("nome", flat=True)) == {"Grande", "Mai"}
    assert segmenti.ricalcola() == 4 and Segmento.objects.get(pk=recenti.pk).numero == 2


def test_pagine_filtro_e_automazioni(s, client):
    azienda, c = s
    client.force_login(User.objects.create_superuser("root", "r@x.it", "x"))
    r = client.post("/contatti/segmenti/nuovo/", {"nome": "Roma", "attivo": "on", "solo_clienti": "on", "province": "RM"})
    assert r.status_code == 302
    seg = Segmento.objects.get(nome="Roma")
    assert seg.numero == 2                                     # ricalcolato al salvataggio
    pagina = client.get(f"/contatti/contatti/?f_segmenti={seg.pk}").content.decode()
    assert "Dormiente" in pagina and "Grande" not in pagina
    assert client.get(f"/contatti/segmenti/{seg.pk}/").status_code == 200
    from automazioni import catalogo, motore
    dominio = next(d for d in catalogo.domini().values() if d.modello == "contatti.Contatto")
    assert motore.vera({"campo": "segmenti", "op": "contiene", "valore": "roma"}, dominio, c["Piccolo"])
    assert not motore.vera({"campo": "segmenti", "op": "contiene", "valore": "roma"}, dominio, c["Grande"])
