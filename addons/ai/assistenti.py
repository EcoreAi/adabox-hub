"""Quale assistente risponde in una conversazione e con quali strumenti.

- Conversazione di un esperto: il suo assistente, fisso.
- Chat limitata a un'app: l'assistente di quell'app (se l'utente è nei suoi gruppi).
- Altre chat: l'assistente predefinito, se c'è. Senza assistente vale il comportamento di base.
Gli esperti lavorano in sola lettura: le modifiche restano proposte dell'assistente principale, che l'utente vede.
"""
from .models import Assistente


def risolvi(conversazione, utente):
    if conversazione.assistente_id:
        a = conversazione.assistente
        return a if a.ammesso(utente) else None
    qs = Assistente.objects.filter(attivo=True).order_by("nome")
    candidati = qs.filter(app=conversazione.ambito) if conversazione.ambito else qs.filter(app="", predefinito=True)
    return next((a for a in candidati if a.ammesso(utente)), None)


def filtra_strumenti(strumenti, assistente, esperto=False):
    """Gli strumenti dell'assistente (tutti se non ne indica) e, per un esperto, solo le letture."""
    if assistente is not None and assistente.strumenti:
        ammessi = set(assistente.strumenti)
        strumenti = [s for s in strumenti if s.nome in ammessi]
    if esperto:
        strumenti = [s for s in strumenti if s.rischio == "lettura" and s.nome != "chiedi_esperto"]
    return strumenti
