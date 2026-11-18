"""Il connettore verso le chat esterne non restituisce dati delle fonti riservate (piano 2026-11-18-chat-riservate)."""
import json

import pytest
from django.contrib.auth.models import User

from connettore_ai import catalogo
from connettore_ai.models import Chiamata, ChatCollegata
from core import parametri

RIFIUTO = "Fonte riservata: si consulta solo dentro adabox, con modelli locali."


@pytest.fixture
def coll(collegata, mario, azienda):
    User.objects.filter(pk=mario.pk).update(is_superuser=True)
    c = ChatCollegata.objects.select_related("utente").get()
    parametri.scrivi("ai.app_riservate", "contatti", azienda)
    return c


def test_vista_riservata_rifiutata(coll):
    esito = catalogo.chiama(coll, "cerca_record", {"vista": "contatti.contatti"})
    assert esito.errore and esito.testo == RIFIUTO
    assert Chiamata.objects.get().esito == Chiamata.RIFIUTATA


def test_misura_riservata_rifiutata(coll, monkeypatch):
    from core import misure
    finta = misure.Misura(nome="contatti.clienti", etichetta="Clienti", definizione="", app="contatti")
    monkeypatch.setattr(misure, "per_nome", lambda nome: finta)
    esito = catalogo.chiama(coll, "misura", {"nome": "contatti.clienti"})
    assert esito.errore and esito.testo == RIFIUTO


def test_documento_riservato_rifiutato(coll, azienda):
    from documenti.models import Cartella, Documento
    cartella = Cartella.objects.create(azienda=azienda, nome="Personale", riservata=True)
    d = Documento.objects.create(azienda=azienda, cartella=cartella, nome="busta.pdf")
    esito = catalogo.chiama(coll, "leggi_documento", {"id": d.pk})
    assert esito.errore and esito.testo == RIFIUTO


def test_conoscenza_filtrata(coll, azienda, monkeypatch):
    from ai.strumenti import registro
    from documenti.models import Cartella, Documento
    riservata = Cartella.objects.create(azienda=azienda, nome="Personale", riservata=True)
    libera = Cartella.objects.create(azienda=azienda, nome="Listini")
    segreto = Documento.objects.create(azienda=azienda, cartella=riservata, nome="busta.pdf")
    pubblico = Documento.objects.create(azienda=azienda, cartella=libera, nome="listino.pdf")
    risultati = [{"n": 1, "vista": "documenti.documenti", "id": segreto.pk, "titolo": "busta"},
                 {"n": 2, "vista": "documenti.documenti", "id": pubblico.pk, "titolo": "listino"},
                 {"n": 3, "vista": "contatti.contatti", "id": 9, "titolo": "Rossi"}]
    monkeypatch.setattr(registro._registro["cerca_conoscenza"], "funzione", lambda contesto, **a: {"risultati": risultati})
    esito = catalogo.chiama(coll, "cerca_conoscenza", {"domanda": "listino"})
    assert not esito.errore
    assert [r["n"] for r in json.loads(esito.testo)["risultati"]] == [2]


def test_app_riservata_non_elencata(coll):
    esito = catalogo.chiama(coll, "app_disponibili", {})
    assert "contatti" not in [r["app"] for r in json.loads(esito.testo)]
