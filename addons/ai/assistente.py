"""Il punto in cui il modulo AI collegherà il modello linguistico. Per ora una risposta segnaposto."""

SEGNAPOSTO = ("L'assistente non è ancora collegato a un modello: il modulo AI arriverà in una prossima versione. "
              "La conversazione intanto viene salvata nella cronologia.")


def rispondi(conversazione, testo):
    """Testo della risposta dell'assistente all'ultimo messaggio dell'utente."""
    return SEGNAPOSTO
