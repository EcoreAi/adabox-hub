"""Smistamento dei file arrivati dallo SDI (dalla PEC o caricati a mano): notifiche, archivi zip."""
import io
import zipfile

from . import notifiche


def ricevi(nome, contenuto, azienda=None):
    """(esito, oggetto): "notifica", "doppione", "zip" o "ignorato"."""
    if nome.lower().endswith(".zip"):
        risultati = []
        with zipfile.ZipFile(io.BytesIO(contenuto)) as archivio:
            for info in archivio.infolist()[:500]:
                if not info.is_dir() and info.file_size < 20 * 1024 * 1024:
                    risultati.append(ricevi(info.filename.rsplit("/", 1)[-1], archivio.read(info), azienda))
        return "zip", risultati
    try:
        notifica, nuova = notifiche.registra(contenuto, nome, azienda)
        return ("notifica" if nuova else "doppione"), notifica
    except notifiche.FileNonRiconosciuto:
        return "ignorato", nome
