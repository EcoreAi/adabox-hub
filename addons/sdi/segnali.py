"""Segnali dello SDI: gli Acquisti, se installati, cercano l'ordine di una fattura appena arrivata."""
from django.dispatch import Signal

fattura_ricevuta = Signal()      # sender=FatturaPassiva, fattura=…, riferimenti={"ordini": […], "ddt": […]}
