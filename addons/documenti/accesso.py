"""Chi vede e chi modifica le cartelle.

- Archivio aziendale (cartelle senza spazio): gruppi della cartella, oppure (se vuoti) quelli ereditati dalla madre.
- Spazi di lavoro: lo spazio personale è del proprietario (e dei responsabili, se l'azienda lo stabilisce); lo spazio
  condiviso è dei suoi membri, con il loro ruolo. I responsabili vedono e modificano gli spazi condivisi.
"""
from .models import Cartella, Documento, MembroSpazio, Spazio


def gestore(user):
    return user.is_superuser or user.has_perm("documenti.vedi_tutte_cartelle")


def responsabili_vedono_personali(azienda):
    from core import parametri
    try:
        valore = parametri.leggi("documenti.responsabili_vedono_personali", azienda)
    except KeyError:
        return True
    return True if valore is None else bool(valore)


def spazi(user, azienda):
    """{spazio: (legge, scrive, gestisce)} degli spazi di lavoro dell'azienda che l'utente vede."""
    if azienda is None or not user.has_perm("documenti.view_documento"):
        return {}
    responsabile = gestore(user)
    personali_ai_responsabili = responsabile and responsabili_vedono_personali(azienda)
    ruoli = dict(MembroSpazio.objects.filter(spazio__azienda=azienda, utente=user).values_list("spazio_id", "ruolo"))
    risultato = {}
    for s in Spazio.objects.filter(azienda=azienda).select_related("proprietario"):
        suo = s.proprietario_id == user.pk
        if s.personale:
            if suo or personali_ai_responsabili:
                risultato[s] = (True, True, suo or personali_ai_responsabili)
        elif suo or responsabile:
            risultato[s] = (True, True, True)
        elif s.pk in ruoli:
            ruolo = ruoli[s.pk]
            risultato[s] = (True, ruolo != MembroSpazio.LETTURA, ruolo == MembroSpazio.GESTIONE)
    return risultato


def _cartelle_spazi(user, azienda, scrittura=False):
    ammessi = [s.pk for s, (legge, scrive, _) in spazi(user, azienda).items() if (scrive if scrittura else legge)]
    return list(Cartella.objects.filter(azienda=azienda, spazio__in=ammessi)) if ammessi else []


def _mappa(azienda):
    """{pk: (cartella, lettura, scrittura)} dell'archivio aziendale con i gruppi effettivi (None = nessun limite)."""
    cartelle = {c.pk: c for c in Cartella.objects.filter(azienda=azienda, spazio__isnull=True)
                .prefetch_related("gruppi_lettura", "gruppi_scrittura")}
    risultato = {}

    def effettivi(c, profondita=0):
        if c.pk in risultato:
            return risultato[c.pk][1:]
        lettura = {g.pk for g in c.gruppi_lettura.all()} or None
        scrittura = {g.pk for g in c.gruppi_scrittura.all()} or None
        madre = cartelle.get(c.padre_id)
        if madre is not None and profondita < 50 and (lettura is None or scrittura is None):
            l_madre, s_madre = effettivi(madre, profondita + 1)
            lettura = lettura if lettura is not None else l_madre
            scrittura = scrittura if scrittura is not None else s_madre
        risultato[c.pk] = (c, lettura, scrittura)
        return lettura, scrittura

    for c in cartelle.values():
        effettivi(c)
    return risultato


def _gruppi(user):
    if not hasattr(user, "_gruppi_documenti"):
        user._gruppi_documenti = set(user.groups.values_list("id", flat=True))
    return user._gruppi_documenti


def _legge(user, lettura, scrittura):
    gruppi = _gruppi(user)
    return lettura is None or bool(lettura & gruppi) or bool(scrittura and scrittura & gruppi)


def _scrive(user, lettura, scrittura):
    gruppi = _gruppi(user)
    return bool(scrittura & gruppi) if scrittura is not None else _legge(user, lettura, scrittura)


def visibili(user, azienda):
    """Le cartelle dell'azienda che l'utente vede: archivio aziendale e spazi di lavoro."""
    if not user.has_perm("documenti.view_documento"):
        return []
    mappa = _mappa(azienda)
    if gestore(user):
        aziendali = [c for c, _, _ in mappa.values()]
    else:
        aziendali = [c for c, lettura, scrittura in mappa.values() if _legge(user, lettura, scrittura)]
    return aziendali + _cartelle_spazi(user, azienda)


def scrivibili(user, azienda):
    if not user.has_perm("documenti.add_documento"):
        return []
    mappa = _mappa(azienda)
    if gestore(user):
        aziendali = [c for c, _, _ in mappa.values()]
    else:
        aziendali = [c for c, lettura, scrittura in mappa.values() if _scrive(user, lettura, scrittura)]
    return aziendali + _cartelle_spazi(user, azienda, scrittura=True)


def puo_scrivere(user, cartella):
    return cartella is not None and cartella.pk in {c.pk for c in scrivibili(user, cartella.azienda)}


def documenti(user, azienda):
    """Queryset dei documenti che l'utente vede (cestino compreso: filtrare dopo)."""
    return Documento.objects.filter(azienda=azienda, cartella__in=[c.pk for c in visibili(user, azienda)])


def puo_modificare(user, documento):
    if documento.bloccato_da_id and documento.bloccato_da_id != user.pk and not gestore(user):
        return False
    return user.has_perm("documenti.change_documento") and puo_scrivere(user, documento.cartella)
