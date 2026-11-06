"""Chi sta scrivendo: la chat collegata al contatto, così l'operatore vede subito con chi parla.

I Contatti sono facoltativi: senza quel modulo la chat funziona come prima. Si collega da solo solo ciò che la
piattaforma garantisce: il numero di WhatsApp, se corrisponde a un unico contatto dell'azienda dello sportello.
L'email scritta nella chat del sito la può digitare chiunque: resta un suggerimento per l'operatore."""
import re

from django.apps import apps
from django.db.models import Q

from .models import Connessione, ConversazioneEsterna

CIFRE_MINIME = 9                                         # meno di così due numeri diversi si confonderebbero
MASSIMO_CERCA = 10


def attivi():
    return apps.is_installed("contatti")


def cifre(numero):
    """Solo le cifre, senza prefisso internazionale scritto con 00."""
    testo = re.sub(r"\D", "", numero or "")
    return testo[2:] if testo.startswith("00") else testo


def stesso_numero(a, b):
    """+39 333 1234567, 0039333... e 3331234567 sono lo stesso numero: conta la parte finale, se è lunga abbastanza."""
    a, b = cifre(a), cifre(b)
    if len(a) < CIFRE_MINIME or len(b) < CIFRE_MINIME:
        return False
    corto, lungo = sorted((a, b), key=len)
    return lungo.endswith(corto) and len(lungo) - len(corto) <= 3


def _contatti_per_numero(azienda, numero):
    from contatti.models import Contatto
    voci = Contatto.objects.filter(azienda=azienda, attivo=True).filter(~Q(telefono="") | ~Q(cellulare=""))
    return [c for c in voci if stesso_numero(c.telefono, numero) or stesso_numero(c.cellulare, numero)]


def contatto_di(conv):
    """Il contatto collegato, se esiste ancora."""
    if not attivi() or conv.contatto_pk is None:
        return None
    from contatti.models import Contatto
    return Contatto.objects.filter(pk=conv.contatto_pk).first()


def riconosci(conv):
    """Alla nascita della conversazione: vale il collegamento già confermato con questa persona, poi il numero."""
    azienda = conv.sportello.azienda
    if not attivi() or azienda is None or conv.contatto_pk is not None:
        return None
    from contatti.models import Contatto
    if conv.connessione_id and conv.id_esterno:
        precedente = (ConversazioneEsterna.objects.filter(connessione=conv.connessione, id_esterno=conv.id_esterno,
                                                          contatto_pk__isnull=False).exclude(pk=conv.pk).order_by("-pk").first())
        if precedente and (c := Contatto.objects.filter(pk=precedente.contatto_pk, azienda=azienda).first()):
            return _salva(conv, c, automatico=precedente.contatto_automatico)
    if conv.connessione_id and conv.connessione.tipo == Connessione.WHATSAPP:
        trovati = _contatti_per_numero(azienda, conv.id_esterno)
        if len(trovati) == 1:
            return _salva(conv, trovati[0], automatico=True)
    return None


def _salva(conv, contatto, automatico=False):
    conv.contatto_pk, conv.contatto_automatico = (contatto.pk if contatto else None), bool(contatto and automatico)
    conv.save(update_fields=["contatto_pk", "contatto_automatico"])
    return contatto


def collega(conv, contatto):
    return _salva(conv, contatto)


def scollega(conv):
    """Tolto da una persona: vale anche per le conversazioni precedenti, che altrimenti lo ripresenterebbero."""
    if conv.connessione_id and conv.id_esterno:
        ConversazioneEsterna.objects.filter(connessione=conv.connessione, id_esterno=conv.id_esterno).update(
            contatto_pk=None, contatto_automatico=False)
    return _salva(conv, None)


def candidati(conv, azienda):
    """I contatti che potrebbero essere questa persona, da confermare: stesso numero o stessa email dichiarata."""
    if not attivi() or azienda is None:
        return []
    from contatti.models import Contatto
    trovati = {}
    if conv.connessione_id and conv.connessione.tipo == Connessione.WHATSAPP:
        trovati.update({c.pk: c for c in _contatti_per_numero(azienda, conv.id_esterno)})
    if conv.email:
        trovati.update({c.pk: c for c in Contatto.objects.filter(azienda=azienda, attivo=True, email__iexact=conv.email)[:MASSIMO_CERCA]})
    return list(trovati.values())[:MASSIMO_CERCA]


def dati_nuovo_contatto(conv):
    dati = {"nome": conv.nome, "email": conv.email, "cliente": True}
    if conv.connessione_id and conv.connessione.tipo == Connessione.WHATSAPP:
        dati["cellulare"] = f"+{cifre(conv.id_esterno)}"
    return dati
