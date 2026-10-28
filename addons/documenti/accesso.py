"""Chi vede e chi modifica le cartelle: gruppi della cartella, oppure (se vuoti) quelli ereditati dalla madre."""
from .models import Cartella, Documento


def gestore(user):
    return user.is_superuser or user.has_perm("documenti.vedi_tutte_cartelle")


def _mappa(azienda):
    """{pk: (cartella, lettura, scrittura)} con i gruppi effettivi (None = nessun limite)."""
    cartelle = {c.pk: c for c in Cartella.objects.filter(azienda=azienda).prefetch_related("gruppi_lettura",
                                                                                          "gruppi_scrittura")}
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
    """Le cartelle dell'azienda che l'utente vede."""
    if not user.has_perm("documenti.view_documento"):
        return []
    mappa = _mappa(azienda)
    if gestore(user):
        return [c for c, _, _ in mappa.values()]
    return [c for c, lettura, scrittura in mappa.values() if _legge(user, lettura, scrittura)]


def scrivibili(user, azienda):
    if not user.has_perm("documenti.add_documento"):
        return []
    mappa = _mappa(azienda)
    if gestore(user):
        return [c for c, _, _ in mappa.values()]
    return [c for c, lettura, scrittura in mappa.values() if _scrive(user, lettura, scrittura)]


def puo_scrivere(user, cartella):
    return cartella is not None and cartella.pk in {c.pk for c in scrivibili(user, cartella.azienda)}


def documenti(user, azienda):
    """Queryset dei documenti che l'utente vede (cestino compreso: filtrare dopo)."""
    return Documento.objects.filter(azienda=azienda, cartella__in=[c.pk for c in visibili(user, azienda)])


def puo_modificare(user, documento):
    if documento.bloccato_da_id and documento.bloccato_da_id != user.pk and not gestore(user):
        return False
    return user.has_perm("documenti.change_documento") and puo_scrivere(user, documento.cartella)
