"""Gateway dei modelli: un'interfaccia sola per Anthropic, endpoint compatibili OpenAI e il modello finto."""
from .esecuzione import esegui  # noqa: F401
from .tipi import (ChiamataStrumento, ErroreModello, Fine, Inizio, Testo, Uso)  # noqa: F401
