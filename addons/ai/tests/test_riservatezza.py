"""Fonti riservate: quali sono e cosa ha letto uno strumento (piano 2026-11-18-chat-riservate)."""
import pytest
from django.contrib.auth.models import User

from ai.models import Conversazione
from core import parametri
from core.models import Azienda


@pytest.fixture
def azienda(db):
    return Azienda.objects.get(pk=1)


def test_campi_e_impostazione_di_partenza(azienda):
    from documenti.models import Cartella
    c = Conversazione.objects.create(utente=User.objects.create_user("u"))
    assert c.riservata is False and c.riservata_motivo == ""
    assert parametri.leggi("ai.app_riservate", azienda) == ""
    assert Cartella.objects.create(azienda=azienda, nome="Archivio").riservata is False
