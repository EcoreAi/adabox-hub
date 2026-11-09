"""Immagini dei prodotti: ridotte e ripulite al caricamento (niente dati EXIF, come la posizione GPS), miniature
generate alla prima richiesta, servite solo a chi vede il prodotto.

I file stanno tra quelli privati; l'URL passa dalla vista `prodotti:immagine`, che controlla i permessi: così il
form, il dettaglio, la lista e l'API mostrano l'immagine senza esporre la cartella."""
import hashlib
import io
import uuid
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils.deconstruct import deconstructible

from core.storage import StoragePrivato

LATO_MASSIMO = 2000            # px: oltre si riduce, basta per stampe e schede
MEGA_MASSIMI = 15              # MB del file caricato
LATI = (64, 200, 600)          # miniature ammesse
FORMATI = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}       # MPO: le foto di alcuni telefoni, sono JPEG


@deconstructible
class StorageImmagini(StoragePrivato):
    """Privato, ma con un URL: quello della vista che controlla chi guarda."""

    def url(self, name):
        return reverse("prodotti:immagine", args=[name])

    def url_miniatura(self, name, lato):
        return f"{self.url(name)}?lato={lato}"

    def delete(self, name):
        super().delete(name)
        for lato in LATI:
            _percorso_miniatura(self, name, lato).unlink(missing_ok=True)


storage = StorageImmagini()


def percorso(istanza, nome):
    """upload_to: prodotti/<azienda>/<casuale>.<estensione decisa da normalizza>."""
    prodotto = getattr(istanza, "prodotto", None) or istanza
    return f"prodotti/{prodotto.azienda_id or 0}/{uuid.uuid4().hex}{Path(nome).suffix.lower() or '.jpg'}"


def valida(file):
    """Validatore del campo: dimensione e formato leggibile."""
    if file and getattr(file, "size", 0) > MEGA_MASSIMI * 1024 * 1024:
        raise ValidationError(f"L'immagine supera i {MEGA_MASSIMI} MB.")
    if file and not getattr(file, "_committed", True):
        _apri(file)


def _apri(file):
    from PIL import Image, UnidentifiedImageError
    try:
        file.seek(0)
        immagine = Image.open(file)
        immagine.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise ValidationError("Il file non è un'immagine leggibile (JPEG, PNG, WebP o GIF).") from e
    if immagine.format not in FORMATI:
        raise ValidationError("Formato non ammesso: carica un JPEG, PNG, WebP o GIF.")
    return immagine


def normalizza(file):
    """ContentFile pronto da salvare: girato secondo l'EXIF, entro LATO_MASSIMO, senza metadati. PNG se ha
    trasparenza, altrimenti JPEG."""
    from PIL import ImageOps
    immagine = ImageOps.exif_transpose(_apri(file))
    immagine.thumbnail((LATO_MASSIMO, LATO_MASSIMO))
    trasparente = immagine.mode in ("RGBA", "LA") or (immagine.mode == "P" and "transparency" in immagine.info)
    uscita = io.BytesIO()
    if trasparente:
        immagine.convert("RGBA").save(uscita, "PNG", optimize=True)
        estensione = ".png"
    else:
        immagine.convert("RGB").save(uscita, "JPEG", quality=85, optimize=True, progressive=True)
        estensione = ".jpg"
    return ContentFile(uscita.getvalue(), name=f"immagine{estensione}")


def prepara(istanza, campo):
    """Da chiamare nel save() del modello: normalizza il file appena caricato e cancella quello che sostituisce.
    Restituisce il nome del file vecchio da cancellare dopo il salvataggio (o None)."""
    valore = getattr(istanza, campo)
    vecchio = None
    if istanza.pk:
        vecchio = type(istanza).objects.filter(pk=istanza.pk).values_list(campo, flat=True).first() or None
    if valore and not valore._committed:
        contenuto = normalizza(valore)
        valore.save(contenuto.name, contenuto, save=False)
    return vecchio if vecchio and vecchio != (valore.name if valore else "") else None


def _percorso_miniatura(archivio, nome, lato):
    impronta = hashlib.sha1(nome.encode()).hexdigest()
    return Path(archivio.path("cache")) / "miniature" / f"{impronta}-{lato}{Path(nome).suffix}"


def miniatura(nome, lato):
    """Percorso della miniatura di lato `lato` (creata alla prima richiesta)."""
    from PIL import Image
    destinazione = _percorso_miniatura(storage, nome, lato)
    if not destinazione.exists():
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(storage.path(nome)) as immagine:
            immagine.thumbnail((lato, lato))
            temporaneo = destinazione.with_suffix(f".{uuid.uuid4().hex}.tmp")
            immagine.save(temporaneo, "PNG" if nome.endswith(".png") else "JPEG", quality=82)
            temporaneo.replace(destinazione)
    return destinazione


def principale(prodotto):
    """Il nome del file dell'immagine da mostrare: la sua, altrimenti la prima della galleria, altrimenti quella
    del prodotto di cui è variante, altrimenti ''."""
    if prodotto.immagine:
        return prodotto.immagine.name
    galleria = sorted(prodotto.immagini.all(), key=lambda i: (i.ordine, i.pk))     # usa il prefetch se c'è
    if galleria:
        return galleria[0].file.name
    if getattr(prodotto, "variante_di_id", None):
        return principale(prodotto.variante_di)
    return ""


def url(prodotto, lato=None):
    nome = principale(prodotto)
    if not nome:
        return ""
    return storage.url_miniatura(nome, lato) if lato else storage.url(nome)


def uri_file(nome):
    """file:// per le stampe con WeasyPrint."""
    return Path(storage.path(nome)).resolve().as_uri() if nome else ""
