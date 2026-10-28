"""Segnali degli acquisti: il magazzino, se installato, crea il ricevimento alla conferma."""
from django.dispatch import Signal

ordine_acquisto_confermato = Signal()      # sender=OrdineAcquisto, ordine=…, utente=…
