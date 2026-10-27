"""Allegati privati: validazione, salvataggio, risposta di download."""
import mimetypes
import os
from pathlib import PurePosixPath

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.utils.http import content_disposition_header
from django.utils.text import get_valid_filename

from .generici import ct_di
from .models import Allegato, Azienda

VIETATE = {"exe", "bat", "cmd", "com", "msi", "scr", "ps1", "vbs", "js", "jar", "dll", "sh", "php", "py",
           "html", "htm", "svg", "hta", "lnk"}
IN_LINEA = {"image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf"}


class AllegatoNonValido(ValueError):
    pass


def nome_pulito(nome):
    nome = get_valid_filename(os.path.basename(nome or "")) or "file"
    radice, est = os.path.splitext(nome)
    return radice[:140] + est[:20]


def valida(file):
    nome = nome_pulito(file.name)
    estensione = PurePosixPath(nome).suffix.lower().lstrip(".")
    if estensione in VIETATE:
        raise AllegatoNonValido(f"«{nome}»: file .{estensione} non ammessi")
    if file.size > settings.ALLEGATI_MAX_MB * 1024 * 1024:
        raise AllegatoNonValido(f"«{nome}»: supera {settings.ALLEGATI_MAX_MB} MB")
    if file.size == 0:
        raise AllegatoNonValido(f"«{nome}»: file vuoto")
    return nome


def salva(obj, file, utente=None):
    """Valida e salva `file` (UploadedFile o File di Django) come allegato di `obj`."""
    nome = valida(file)
    azienda = getattr(obj, "azienda", None)
    return Allegato.objects.create(
        content_type=ct_di(obj), object_id=obj.pk, file=_con_nome(file, nome), nome=nome,
        mime=mimetypes.guess_type(nome)[0] or "application/octet-stream", dimensione=file.size,
        caricato_da=utente if utente is not None and utente.is_authenticated else None,
        azienda=azienda if isinstance(azienda, Azienda) else None)


def _con_nome(file, nome):
    file.name = nome
    return file


def di(obj):
    return Allegato.objects.filter(content_type=ct_di(obj), object_id=obj.pk)


def risposta(allegato):
    """FileResponse, o X-Accel-Redirect verso la location internal di nginx se ALLEGATI_X_ACCEL."""
    in_linea = allegato.mime in IN_LINEA
    if settings.ALLEGATI_X_ACCEL:
        r = HttpResponse(content_type=allegato.mime)
        r["X-Accel-Redirect"] = f"/_privati/{allegato.file.name}"
        r["Content-Disposition"] = content_disposition_header(not in_linea, allegato.nome)
        return r
    return FileResponse(allegato.file.open("rb"), as_attachment=not in_linea, filename=allegato.nome,
                        content_type=allegato.mime)
