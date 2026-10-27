import signal
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from core import lavori


def impronta_moduli():
    """Date di modifica di installed.json e dei manifest: se cambiano, il processo ha moduli vecchi."""
    radice = Path(settings.ADDONS_DIR)
    file = [radice / "installed.json", *sorted(radice.glob("*/__manifest__.py"))]
    return tuple((str(f), f.stat().st_mtime_ns) for f in file if f.exists())


class Command(BaseCommand):
    help = "Esegue i lavori in background e le pianificazioni (in produzione: un container dedicato)"

    def add_arguments(self, parser):
        parser.add_argument("--una-volta", action="store_true", help="esegue i lavori pronti ed esce")
        parser.add_argument("--pausa", type=float, default=2.0, help="secondi di attesa a coda vuota")

    def handle(self, una_volta, pausa, **_):
        self.fermati = False
        if not una_volta:
            signal.signal(signal.SIGTERM, self._ferma)
            signal.signal(signal.SIGINT, self._ferma)
            self.stdout.write("worker avviato")
        if n := lavori.sblocca():
            self.stdout.write(f"rimessi in coda {n} lavori bloccati")
        impronta = impronta_moduli()
        while not self.fermati:
            if impronta_moduli() != impronta:
                # moduli installati o aggiornati: si esce e il supervisore (Docker) riavvia con il codice nuovo
                self.stdout.write("moduli cambiati: il worker si ferma per ripartire con il codice nuovo")
                break
            self._pianifica()
            lavoro = lavori.esegui_uno()
            if lavoro is not None:
                self.stdout.write(f"{lavoro}: {lavoro.stato}")
                continue
            if una_volta:
                break
            self._dormi(pausa)
        if not una_volta:
            self.stdout.write("worker fermato")

    def _pianifica(self):
        pianifica = getattr(lavori, "pianifica_scadute", None)
        if pianifica:
            pianifica()

    def _ferma(self, *_):
        self.fermati = True                  # finisce il lavoro in corso, poi esce

    def _dormi(self, pausa):
        fine = time.monotonic() + pausa
        while not self.fermati and time.monotonic() < fine:
            time.sleep(min(0.2, pausa))
