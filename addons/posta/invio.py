"""I messaggi del chatter ai clienti partono dalla casella di chi li scrive (CRM-08): il cliente vede la persona, non
il server, e risponde a lei; la risposta torna nello storico dal giro della posta, abbinata al record dal Message-ID.
Se la casella non può (permesso mancante, errore), il messaggio parte dal server come sempre."""
import logging
from email.utils import formataddr

from . import fornitori
from .fornitori.base import ErrorePosta
from .models import Casella

log = logging.getLogger("posta.invio")


def casella_per(messaggio):
    """La casella dell'autore che può inviare: prima quella dell'azienda del record."""
    if messaggio.autore_id is None:
        return None
    azienda_id = getattr(messaggio.record, "azienda_id", None)
    caselle = sorted(Casella.objects.filter(utente_id=messaggio.autore_id, invio=True, in_errore=False).select_related("utente"),
                     key=lambda c: (c.azienda_id != azienda_id, c.pk))
    for casella in caselle:
        try:
            if fornitori.di(casella).puo_inviare(casella.ambiti):
                return casella
        except ErrorePosta:
            continue
    return None


def invia(messaggio, email):
    """Registrata in core.chatter.email: True se l'email è partita dalla casella dell'autore."""
    from .sincronia import esito
    casella = casella_per(messaggio)
    if casella is None:
        return False
    mime = email.message()
    nome = casella.utente.get_full_name() or casella.utente.username
    del mime["From"]
    mime["From"] = formataddr((nome, casella.email))
    del mime["Reply-To"]                              # le risposte tornano alla persona, non all'indirizzo di sistema
    try:
        fornitori.di(casella).invia(mime.as_bytes())
    except ErrorePosta as e:
        esito(casella, f"Invio dal chatter non riuscito, partito dal server: {e}", errore=not isinstance(e, fornitori.ErroreTemporaneo))
        return False
    return True
