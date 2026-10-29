"""Segnali dei Documenti per chi li segue (es. l'indice dell'assistente AI), anche per le modifiche di massa che non
passano da save(): spostamento, cestino, ripristino."""
from django.dispatch import Signal

documenti_cambiati = Signal()          # kwargs: pks (lista di id dei documenti)
