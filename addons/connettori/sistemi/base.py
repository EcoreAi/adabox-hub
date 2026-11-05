"""Ciò che vale per tutti i sistemi esterni."""


class ErroreConnettore(RuntimeError):
    """Serve una persona: token sbagliato, dato rifiutato. Ritentare non aiuta."""


class ErroreTemporaneo(ErroreConnettore):
    """Rete, troppe richieste, server in difficoltà: si riprova più tardi."""
