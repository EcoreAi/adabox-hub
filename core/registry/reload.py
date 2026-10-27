"""Ricarica del server dopo un cambio di moduli (RELOAD_STRATEGY)."""
import os
import signal
from pathlib import Path

from django.conf import settings


class RicaricaNonDisponibile(Exception):
    pass


def richiedi():
    """Chiede al server di ricaricare il codice. True se ha fatto qualcosa."""
    strategia = settings.RELOAD_STRATEGY
    if strategia == "none":
        return False
    if strategia == "gunicorn":
        pidfile = Path(settings.GUNICORN_PIDFILE)
        if not pidfile.is_file():
            raise RicaricaNonDisponibile(f"pidfile {pidfile} assente: riavvia gunicorn a mano")
        os.kill(int(pidfile.read_text().strip()), signal.SIGHUP)
        return True
    if strategia == "runserver":
        os.utime(Path(settings.BASE_DIR) / "config" / "settings.py")   # lo StatReloader riavvia
        return True
    raise ValueError(f"RELOAD_STRATEGY {strategia!r} sconosciuta")
