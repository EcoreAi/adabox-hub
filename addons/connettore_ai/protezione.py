"""Dati personali verso le chat esterne: con l'impostazione dell'azienda accesa, i testi dei risultati escono con i
segnaposto dell'assistente ([FULLNAME_1]) e i segnaposto negli argomenti tornano valori veri.

I segnaposto sono stabili per collegamento e stanno sul server, perché il protocollo non ha sessioni: la chat può
cercare «le fatture di [FULLNAME_1]» anche giorni dopo. È pseudonimizzazione: riduce il rischio, non rende i dati
anonimi. Se il servizio non risponde non esce nulla."""
from django.db import transaction

from .models import ChatCollegata


class NonDisponibile(Exception):
    pass


def attiva(collegamento):
    from core import parametri
    return bool(parametri.leggi("connettore_ai.maschera", collegamento.azienda))


def _stringhe(valore, funzione):
    if isinstance(valore, str):
        return funzione(valore)
    if isinstance(valore, list):
        return [_stringhe(v, funzione) for v in valore]
    if isinstance(valore, dict):
        return {k: _stringhe(v, funzione) for k, v in valore.items()}
    return valore


def smaschera(collegamento, argomenti):
    """Gli argomenti con i valori veri al posto dei segnaposto già dati a questo collegamento (anche se nel frattempo
    la protezione è stata spenta: la chat ha ancora in mano i segnaposto di prima)."""
    if not collegamento.segnaposto:
        return argomenti
    from ai.protezione import Vault
    vault = Vault(collegamento.segnaposto)
    return _stringhe(argomenti, lambda testo: vault.smaschera(testo)[0])


def maschera(collegamento, testo):
    """(testo mascherato, quanti dati protetti). La rete sta fuori dalla transazione; i segnaposto si assegnano con il
    collegamento bloccato, così due chiamate insieme non danno lo stesso numero a due valori diversi."""
    if not attiva(collegamento) or not testo.strip():
        return testo, 0
    from ai import protezione as di_ada
    url, esclusi = di_ada.impostazioni()
    if not url:
        raise NonDisponibile("servizio di protezione dei dati personali non configurato")
    try:
        intervalli = sorted(di_ada.spans(url, testo, esclusi))
    except di_ada.ServizioNonDisponibile as e:
        raise NonDisponibile(str(e)) from e
    with transaction.atomic():
        riga = ChatCollegata.objects.select_for_update().get(pk=collegamento.pk)
        vault = di_ada.Vault(riga.segnaposto)
        pezzi, posizione, trovati = [], 0, 0
        for inizio, fine, etichetta in intervalli:
            if inizio < posizione or not di_ada.plausibile(testo, inizio, fine, etichetta):
                continue
            pezzi += [testo[posizione:inizio], vault.segnaposto(etichetta, testo[inizio:fine])]
            posizione, trovati = fine, trovati + 1
        pezzi.append(testo[posizione:])
        if vault.nuovi:
            riga.segnaposto = vault.mappa
            riga.save(update_fields=["segnaposto"])
    collegamento.segnaposto = vault.mappa
    return "".join(pezzi), trovati
