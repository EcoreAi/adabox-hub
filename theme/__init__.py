"""Il tema grafico. Due funzioni per gli altri moduli:

- `per_azienda(request, azienda)`: nelle pagine senza login, il tema (e i template) dell'azienda del documento;
- `marchio(azienda)`: il nome del prodotto per le email spedite per conto di un'azienda."""


def per_azienda(request, azienda):
    """Da chiamare nella vista prima del render: la pagina prende il tema dell'azienda (non cambia request.azienda)."""
    request.azienda_tema = azienda
    if hasattr(request, "_tema_grafico"):
        del request._tema_grafico


def marchio(azienda=None):
    """Il nome del prodotto: quello del tema dell'azienda, altrimenti del tema attivo, altrimenti THEME["brand"]."""
    from django.conf import settings

    from .models import Tema
    try:
        tema = None
        if azienda is not None and getattr(azienda, "tema_id", None):
            tema = Tema.objects.filter(pk=azienda.tema_id).only("marchio").first()
        if tema is None:
            tema = Tema.objects.filter(attivo=True).only("marchio").first()
    except Exception:                          # tabella mancante (prima delle migrazioni)
        tema = None
    return (tema.marchio if tema and tema.marchio else "") or settings.THEME.get("brand", "")
