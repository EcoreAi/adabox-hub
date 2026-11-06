"""Segnali del timesheet."""
from django.dispatch import Signal

cronometro_fermato = Signal()      # sender=RigaOre, riga=…, ticket_id=…
