"""Il tema grafico. Funzioni per gli altri moduli:

- `per_azienda(request, azienda)`: nelle pagine senza login, il tema (e i template) dell'azienda del documento;
- `marchio(azienda)`: il nome del prodotto per le email spedite per conto di un'azienda;
- `tema_del_modulo(nome, ...)`: il tema di un modulo che porta la sua grafica, dal suo hook post_install;
- `modulo_del_tema(azienda)`: di quale modulo sono i template del tema dell'azienda."""


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


LOGO_ESTENSIONI = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".webp": "image/webp"}
LOGO_MAX = 256 * 1024


def tema_del_modulo(nome, *, template="", foglio="", logo="", marchio="", colore_barra="", descrizione=""):
    """Per l'hook `post_install` di un modulo che porta la sua grafica: crea (o aggiorna, se c'è già) il tema `nome`.

    - `template`: il pacchetto con i template del modulo (es. "iem.tema");
    - `foglio`: un CSS tra gli statici del modulo (es. "iem/tema/iem.css"), servito come file: i suoi url() relativi
      (font, immagini) funzionano;
    - `logo`: un'immagine tra gli statici del modulo, copiata nel tema (SVG, PNG, JPG o WebP fino a 256 KB).
    Non attiva il tema e non lo assegna a nessuna azienda: lo sceglie chi amministra, nella scheda dell'azienda."""
    from pathlib import Path

    from django.contrib.staticfiles import finders

    from .models import Tema
    from .template_tema import cartella
    if template and cartella(template) is None:
        raise ValueError(f"template {template!r}: serve il pacchetto di un modulo attivo con una cartella templates")
    if foglio and not finders.find(foglio):
        raise ValueError(f"foglio {foglio!r}: non è tra gli statici")
    valori = {"template": template, "foglio": foglio, "marchio": marchio, "colore_barra": colore_barra,
              "descrizione": descrizione}
    if logo:
        file = finders.find(logo)
        tipo = LOGO_ESTENSIONI.get(Path(logo).suffix.lower())
        if not file or not tipo:
            raise ValueError(f"logo {logo!r}: serve un'immagine SVG, PNG, JPG o WebP tra gli statici")
        dati = Path(file).read_bytes()
        if len(dati) > LOGO_MAX:
            raise ValueError(f"logo {logo!r}: supera 256 KB")
        valori.update(logo=dati, logo_tipo=tipo)
    tema, _ = Tema.objects.update_or_create(nome=nome, defaults=valori)
    return tema


def modulo_del_tema(azienda):
    """Lo slug del modulo i cui template usa il tema dell'azienda ("zenpark" con Template = "zenpark.tema"), o "".
    Per le personalizzazioni che un modulo applica solo alle aziende con la sua grafica."""
    from .models import Tema
    if azienda is None or not getattr(azienda, "tema_id", None):
        return ""
    template = Tema.objects.filter(pk=azienda.tema_id).values_list("template", flat=True).first() or ""
    return template.split(".")[0] if template else ""
