"""Segnali dell'helpdesk per chi lo estende (es. l'assistenza per progetto)."""
from django.dispatch import Signal

ticket_da_email = Signal()          # kwargs: ticket (appena aperto da un'email, ancora senza team)
