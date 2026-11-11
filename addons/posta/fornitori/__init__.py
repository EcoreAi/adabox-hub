"""I servizi di posta e calendario gestiti."""
from .base import ErrorePosta, ErroreTemporaneo  # noqa: F401
from .google import Google
from .microsoft import Microsoft

FORNITORI = {"google": Google, "microsoft": Microsoft}
TRASPORTO = None          # nei test: un servizio simulato al posto della rete


def per(servizio, casella=None):
    return FORNITORI[servizio.tipo](servizio, casella, transport=TRASPORTO)


def di(casella):
    """Il fornitore di una casella, con l'applicazione dell'istanza. ErrorePosta se il servizio è stato tolto."""
    from ..models import ServizioOAuth
    servizio = ServizioOAuth.objects.filter(tipo=casella.tipo, attivo=True).first()
    if servizio is None:
        raise ErrorePosta(f"Il collegamento con {casella.get_tipo_display()} non è più configurato: chiedi all'amministratore.")
    return per(servizio, casella)
