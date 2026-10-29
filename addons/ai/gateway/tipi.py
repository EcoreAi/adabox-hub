"""Pezzi normalizzati dello stream di un modello, errori normalizzati e formato neutro dei messaggi.

Messaggi neutri (quelli del log degli eventi):
- {"ruolo": "utente", "testo": "..."}
- {"ruolo": "assistente", "blocchi": [{"tipo": "testo", "testo": ...} | {"tipo": "strumento", "id", "nome",
   "argomenti"}], "nativo": {"provider": "anthropic", "contenuto": [...]}}   # nativo: da rimandare invariato
- {"ruolo": "strumento", "risultati": [{"id", "contenuto": str, "errore": bool}]}
"""
from dataclasses import dataclass, field


@dataclass
class Inizio:
    modello: object                       # ai.models.Modello in uso


@dataclass
class Testo:
    __test__ = False                      # il nome inizia con "Test": pytest non deve raccoglierla
    testo: str


@dataclass
class ChiamataStrumento:
    id: str
    nome: str
    argomenti: dict


@dataclass
class Uso:
    input: int = 0
    output: int = 0
    cache_scrittura: int = 0
    cache_lettura: int = 0

    def come_dict(self):
        return {"input": self.input, "output": self.output, "cache_scrittura": self.cache_scrittura,
                "cache_lettura": self.cache_lettura}


@dataclass
class Fine:
    motivo: str                           # fine | strumenti | limite | rifiuto | altro
    blocchi: list = field(default_factory=list)
    nativo: dict | None = None


class ErroreModello(Exception):
    """codice: RATE_LIMIT, SERVER, RETE, TIMEOUT, AUTENTICAZIONE, RICHIESTA, CONTESTO, VUOTA, CONFIGURAZIONE."""
    RIPROVABILI = {"RATE_LIMIT", "SERVER", "RETE", "TIMEOUT", "VUOTA"}

    def __init__(self, codice, messaggio="", attesa=None):
        super().__init__(f"{codice}: {messaggio}" if messaggio else codice)
        self.codice, self.messaggio, self.attesa = codice, messaggio, attesa

    @property
    def riprovabile(self):
        return self.codice in self.RIPROVABILI
