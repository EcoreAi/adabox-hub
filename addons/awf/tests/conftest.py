import hashlib
import json

import pytest

from awf import fabbrica
from awf.models import Collegamento, OperazioneAmmessa
from core import cifratura
from core.models import Azienda

BEARER = "awf_bearer-di-prova-abcdefghijklmnopqrstuvwxyz"
AGENTI = [{"name": "Buyer", "role": "coordinator", "agate_agent_id": "agt_buyer"},
          {"name": "Magazziniere", "role": "operativo", "agate_agent_id": "agt_mag"}]


class Fabbrica:
    """Trasporto HTTP finto: registra le richieste e risponde con le risposte preparate per percorso."""

    def __init__(self):
        self.richieste = []
        self.risposte = {}

    def __call__(self, metodo, url, intestazioni, corpo, timeout):
        self.richieste.append({"metodo": metodo, "url": url, "intestazioni": intestazioni,
                               "corpo": json.loads(corpo) if corpo else None, "grezzo": corpo or b""})
        percorso = url.split("://", 1)[1].split("/", 1)[1]
        stato, risposta = self.risposte.get("/" + percorso, (404, {}))
        if isinstance(stato, Exception):
            raise stato
        return stato, json.dumps(risposta).encode()


@pytest.fixture
def finta(monkeypatch):
    f = Fabbrica()
    monkeypatch.setattr(fabbrica, "trasporto", f)
    return f


def ingaggio(**altro):
    return {"id": "eng_1", "title": "Acquisti", "status": "active", "blocked": None, "days_left": 5,
            "observe_until": None, "agents": AGENTI, "agate_console_url": "https://agate.esempio.it/console/engagements/eng_1/",
            **altro}


@pytest.fixture
def collegato(db):
    azienda = Azienda.objects.get(pk=1)
    c = Collegamento.attuale()
    c.forge_url, c.base_url = "https://fabbrica.esempio.it", "https://erp.esempio.it"
    c.token_cifrato = cifratura.cifra("wpt_token-della-fabbrica")
    c.mcp_impronta = hashlib.sha256(BEARER.encode()).hexdigest()
    c.ultimo_stato, c.azienda = ingaggio(), azienda
    c.save()
    from awf import agenti
    agenti.sincronizza(c.ultimo_stato, azienda)
    return c


@pytest.fixture
def ammesse(db):
    """Letture generiche, più lettura e scrittura sulle attività di To-Do."""
    for strumento, vista in [("elenco_viste", ""), ("cerca_record", ""), ("leggi_record", "todo.attivita"),
                             ("modifica_record", "todo.attivita"), ("crea_record", "todo.attivita")]:
        OperazioneAmmessa.objects.create(strumento=strumento, vista=vista)
