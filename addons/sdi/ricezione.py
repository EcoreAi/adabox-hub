"""Smistamento dei file arrivati dallo SDI (dalla PEC o caricati a mano): notifiche, archivi zip."""
import io
import zipfile

from . import notifiche, passive


def ricevi(nome, contenuto, azienda=None):
    """(esito, oggetto): "notifica", "passiva" (fattura di un fornitore), "doppione", "zip" o "ignorato"."""
    if nome.lower().endswith(".zip"):
        risultati = []
        with zipfile.ZipFile(io.BytesIO(contenuto)) as archivio:
            for info in archivio.infolist()[:500]:
                if not info.is_dir() and info.file_size < 20 * 1024 * 1024:
                    risultati.append(ricevi(info.filename.rsplit("/", 1)[-1], archivio.read(info), azienda))
        return "zip", risultati
    if nome.lower().endswith(".p7m") or passive.e_fattura(contenuto):
        try:
            risultati = passive.importa(nome, contenuto, azienda)
        except passive.FatturaNonValida:
            return "ignorato", nome
        nuove = [f for f, nuova in risultati if nuova]
        return ("passiva", nuove[0]) if nuove else ("doppione", risultati[0][0])
    try:
        notifica, nuova = notifiche.registra(contenuto, nome, azienda)
    except notifiche.FileNonRiconosciuto:
        return "ignorato", nome
    if nuova:
        passive.collega_metadati(notifica)
    return ("notifica" if nuova else "doppione"), notifica
