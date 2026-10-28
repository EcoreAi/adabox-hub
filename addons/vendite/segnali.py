"""Segnali delle vendite: le altre app (magazzino, fatturazione) li ascoltano se sono installate."""
from django.dispatch import Signal

ordine_confermato = Signal()        # sender=OrdineVendita, ordine=…, utente=…
