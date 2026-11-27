"""Backup del database prima di installare, aggiornare o disinstallare moduli."""
import logging
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.db import connection
from django.utils import timezone

log = logging.getLogger("core.moduli")


class BackupFallito(Exception):
    pass


def _sqlite(dest):
    """Va chiamata fuori da transazioni con scritture non committate: il backup nativo di sqlite
    sulla stessa connessione resterebbe in attesa (succede solo nei test non transazionali)."""
    connection.ensure_connection()
    destinazione = sqlite3.connect(dest)
    try:
        connection.connection.backup(destinazione)   # API nativa: funziona anche sul DB in memoria dei test
    finally:
        destinazione.close()


def _postgres(dest, db):
    host = db.get("HOST") or "localhost"
    porta = f":{db['PORT']}" if db.get("PORT") else ""
    url = f"postgresql://{quote(db.get('USER') or '', safe='')}@{host}{porta}/{quote(db['NAME'], safe='')}"
    esito = subprocess.run(["pg_dump", "-Fc", "--dbname", url, "--file", str(dest)],
                           env={**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""},
                           capture_output=True, text=True)
    if esito.returncode != 0:
        raise BackupFallito(f"pg_dump fallito: {esito.stderr.strip()}")


LUNGHEZZA_MOTIVO = 150
AUTOMATICO = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}-.+\.(sqlite3|dump)")     # il nome che dà esegui()


def esegui(motivo):
    """Copia il DB in BACKUP_DIR/<AAAA-MM-GG-HHMMSS>-<motivo>.<sqlite3|dump>. Restituisce il Path."""
    db = settings.DATABASES["default"]
    engine = db["ENGINE"]
    cartella = Path(settings.BACKUP_DIR)
    data = timezone.localtime().strftime("%Y-%m-%d-%H%M%S")
    motivo = motivo[:LUNGHEZZA_MOTIVO]                  # con molti moduli insieme il nome supererebbe il limite del disco
    try:
        cartella.mkdir(parents=True, exist_ok=True)
        if "sqlite3" in engine:
            dest = cartella / f"{data}-{motivo}.sqlite3"
            _sqlite(dest)
        elif "postgresql" in engine:
            dest = cartella / f"{data}-{motivo}.dump"
            _postgres(dest, db)
        else:
            raise BackupFallito(f"backup non supportato per il database {engine}")
    except (OSError, sqlite3.Error) as e:
        raise BackupFallito(f"backup fallito: {e}") from e
    log.info("backup creato: %s", dest)
    pulisci()
    return dest


def pulisci():
    """Tiene solo gli ultimi BACKUP_CONSERVA backup automatici (il nome inizia con la data, quindi per nome sono in
    ordine di tempo). Gli altri file della cartella, come le copie fatte a mano, non li tocca: quando si ordinava
    tutto insieme, i «db-…» finivano dopo i «2026-…» e a farne le spese era il backup appena creato."""
    cartella = Path(settings.BACKUP_DIR)
    if not cartella.is_dir():
        return
    file = sorted(p for p in cartella.iterdir() if p.is_file() and AUTOMATICO.fullmatch(p.name))
    for vecchio in file[:-settings.BACKUP_CONSERVA] if settings.BACKUP_CONSERVA > 0 else []:
        vecchio.unlink()
        log.info("backup rimosso: %s", vecchio)
