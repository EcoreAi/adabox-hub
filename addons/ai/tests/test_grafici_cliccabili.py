"""Grafici cliccabili in chat: ogni punto porta il link ai record che lo formano, oppure niente se l'elenco non sa
filtrarli (un link che mostra altri record sarebbe una bugia)."""
import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from ai import artifact, strumenti
from ai.models import Artifact, Conversazione
from core.models import Azienda
from todo.models import Attivita


@pytest.fixture
def contesto(db):
    capo = User.objects.create_superuser("capo", "capo@example.com", "x")
    return strumenti.Contesto(utente=capo, azienda=Azienda.objects.get(pk=1),
                              conversazione=Conversazione.objects.create(utente=capo, titolo="Grafici"))


def _attivita(stato, n=1, **campi):
    for i in range(n):
        Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo=f"{stato} {i}", stato=stato, **campi)


def _link(r):
    return Artifact.objects.get(pk=r["artifact"]).dati["link"]


def test_grafico_per_stato_ha_un_link_per_barra(contesto):
    _attivita("aperta", 3)
    _attivita("fatta", 1)
    r = artifact.grafico(contesto, vista="todo.attivita", per="stato")
    lista = reverse("todo:attivita_lista")
    assert [e for e, _ in r["serie"]] == ["Aperta", "Fatta"]
    assert _link(r) == [lista + "?f_stato=aperta", lista + "?f_stato=fatta"]


def test_primi_altro_senza_link(contesto):
    _attivita("aperta", 3)
    _attivita("fatta", 2)
    _attivita("in_corso", 1)
    r = artifact.grafico(contesto, vista="todo.attivita", per="stato", primi=1)
    assert [e for e, _ in r["serie"]] == ["Aperta", "Altro"]
    assert _link(r) == [reverse("todo:attivita_lista") + "?f_stato=aperta", None]


def test_gruppo_senza_valore_non_sposta_gli_altri_link(contesto):
    _attivita("aperta", 2)
    _attivita("aperta", 1, assegnatario=contesto.utente)
    r = artifact.grafico(contesto, vista="todo.attivita", per="assegnatario")
    coppie = list(zip(r["serie"], _link(r)))
    assert len(coppie) == 2
    for (etichetta, valore), link in coppie:                              # ogni link resta accanto al suo punto
        if valore == 1:
            assert link == reverse("todo:attivita_lista") + f"?f_assegnatario={contesto.utente.pk}"
        else:
            assert link is None                                           # il gruppo «nessuno» non ha link


def test_campo_che_la_lista_non_filtra_niente_link(contesto):
    import datetime
    _attivita("aperta", 2, scadenza=datetime.date(2026, 11, 3))
    r = artifact.grafico(contesto, vista="todo.attivita", per="scadenza:mese", tipo="linee")
    assert r["serie"] and _link(r) == [None] * len(r["serie"])


def test_aggiorna_ricalcola_i_link(contesto):
    _attivita("aperta", 1)
    r = artifact.grafico(contesto, vista="todo.attivita", per="stato")
    a = Artifact.objects.get(pk=r["artifact"])
    _attivita("fatta", 1)
    assert len(artifact.ricalcola(a)["link"]) == 2
