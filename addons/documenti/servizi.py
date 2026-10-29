"""Operazioni sui documenti: caricamento, spostamento, cestino, archivio zip."""
import io
import mimetypes
import os
import zipfile

from django.db import transaction
from django.utils import timezone

from core import allegati

from . import quote
from .models import Documento, Versione

LIMITE_ZIP_MB = 500


def nome_visibile(nome):
    """Il nome originale (spazi e accenti compresi) senza percorso né caratteri di controllo."""
    nome = os.path.basename(str(nome or "").replace("\\", "/"))
    return "".join(c for c in nome if c.isprintable()).strip()[:200]


def carica(cartella, file, utente=None, **altri):
    """Valida (regole degli allegati del kernel, dimensione massima dell'azienda), controlla le quote e archivia
    `file` in `cartella`. Un file con lo stesso nome di un documento della cartella ne diventa la versione nuova."""
    su_disco = allegati.valida(file, max_mb=quote.max_file_mb(cartella.azienda))
    nome = nome_visibile(file.name) or su_disco
    try:
        quote.controlla(cartella, file.size)
    except quote.QuotaSuperata as e:
        raise allegati.AllegatoNonValido(f"«{nome}»: {e}")
    file.name = su_disco
    autore = utente if utente is not None and utente.is_authenticated else None
    esistente = (Documento.objects.filter(cartella=cartella, nome=nome, cestinato_il__isnull=True,
                                          allegato__isnull=True).exclude(file="").first()
                 if quote.parametro("versioni_max", cartella.azienda, 10) else None)
    if esistente is not None and not altri:
        return nuova_versione(esistente, file, autore)
    return Documento.objects.create(azienda=cartella.azienda, cartella=cartella, nome=nome, file=file,
                                    mime=mimetypes.guess_type(nome)[0] or "application/octet-stream",
                                    dimensione=file.size, proprietario=autore, caricato_da=autore, **altri)


@transaction.atomic
def nuova_versione(documento, file, utente=None):
    """Il file attuale diventa una versione salvata, `file` il contenuto attuale; si tengono le ultime N."""
    if documento.bloccato_da_id and utente is not None and documento.bloccato_da_id != utente.pk:
        raise allegati.AllegatoNonValido(f"«{documento}» è bloccato da {documento.bloccato_da}: non si sovrascrive")
    Versione.objects.create(documento=documento, numero=documento.versione, file=documento.file.name,
                            dimensione=documento.dimensione, caricata_da=documento.caricato_da or documento.proprietario,
                            creata=documento.modificato)
    documento.file, documento.dimensione = file, file.size
    documento.mime = mimetypes.guess_type(documento.nome)[0] or documento.mime
    documento.versione, documento.caricato_da = documento.versione + 1, utente
    documento.save()
    _sfoltisci(documento)
    return documento


def _sfoltisci(documento):
    massimo = int(quote.parametro("versioni_max", documento.azienda, 10))
    for vecchia in documento.versioni.all()[massimo:]:
        vecchia.file.delete(save=False)
        vecchia.delete()


@transaction.atomic
def ripristina_versione(versione, utente=None):
    """La versione scelta torna il contenuto attuale (come versione nuova: niente si perde)."""
    from django.core.files.base import ContentFile
    documento = versione.documento
    with versione.file.open("rb") as f:
        contenuto = ContentFile(f.read(), name=os.path.basename(versione.file.name).split("-", 1)[-1])
    try:
        quote.controlla(documento.cartella, contenuto.size)
    except quote.QuotaSuperata as e:
        raise allegati.AllegatoNonValido(f"«{documento}»: {e}")
    return nuova_versione(documento, contenuto, utente)


def risposta(documento, in_linea=True):
    """Download con le regole degli allegati del kernel (X-Accel in produzione)."""
    finto = type("File", (), {"mime": documento.mime if in_linea else "application/octet-stream",
                              "file": documento.contenuto, "nome": documento.nome})()
    return allegati.risposta(finto)


def sposta(documenti, cartella):
    return Documento.objects.filter(pk__in=[d.pk for d in documenti]).update(cartella=cartella, azienda=cartella.azienda)


def cestina(documenti):
    return Documento.objects.filter(pk__in=[d.pk for d in documenti], cestinato_il__isnull=True).update(
        cestinato_il=timezone.now())


def ripristina(documenti):
    return Documento.objects.filter(pk__in=[d.pk for d in documenti]).update(cestinato_il=None)


@transaction.atomic
def elimina(documenti):
    """Eliminazione definitiva (solo dal cestino): via il record, le versioni e, se è suo, il file."""
    n = 0
    for d in documenti:
        if d.cestinato_il is None:
            continue
        for v in d.versioni.all():
            v.file.delete(save=False)
        if d.file and not d.allegato_id:
            d.file.delete(save=False)
        d.delete()
        n += 1
    return n


def zip_di(documenti):
    """Bytes di un archivio zip con i documenti (nomi doppi resi unici)."""
    totale = sum(d.dimensione for d in documenti)
    if totale > LIMITE_ZIP_MB * 1024 * 1024:
        raise ValueError(f"La selezione supera {LIMITE_ZIP_MB} MB: scarica meno documenti alla volta.")
    buffer, usati = io.BytesIO(), set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archivio:
        for d in documenti:
            nome, n = d.nome, 1
            while nome in usati:
                radice, punto, est = d.nome.rpartition(".")
                nome = f"{radice or d.nome} ({n}){punto}{est if radice else ''}"
                n += 1
            usati.add(nome)
            with d.contenuto.open("rb") as f:
                archivio.writestr(nome, f.read())
    return buffer.getvalue()


def spazio_usato(azienda):
    from django.db.models import Sum
    return Documento.objects.filter(azienda=azienda, allegato__isnull=True).aggregate(t=Sum("dimensione"))["t"] or 0

