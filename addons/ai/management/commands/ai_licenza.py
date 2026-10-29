"""Emette un file di licenza del modulo AI (da usare in ICHNOBYTE con la chiave privata dei pacchetti)."""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from core.registry import pacchetti

from ai import licenza


class Command(BaseCommand):
    help = "Genera un file di licenza firmato per il modulo AI"

    def add_arguments(self, parser):
        parser.add_argument("--chiave", required=True, help="chiave privata PEM di ICHNOBYTE")
        parser.add_argument("--cliente", required=True)
        parser.add_argument("--scadenza", required=True, help="AAAA-MM-GG")
        parser.add_argument("--utenti", type=int, default=0, help="utenti al mese (0 = senza limite)")
        parser.add_argument("--funzioni", default=",".join(licenza.FUNZIONI))
        parser.add_argument("--uscita", help="file da scrivere (default: stampa)")

    def handle(self, *args, **opzioni):
        try:
            datetime.date.fromisoformat(opzioni["scadenza"])
        except ValueError as e:
            raise CommandError("scadenza non valida (AAAA-MM-GG)") from e
        dati = licenza.firma({"cliente": opzioni["cliente"], "emessa": datetime.date.today().isoformat(),
                              "scadenza": opzioni["scadenza"], "utenti": opzioni["utenti"],
                              "funzioni": [f.strip() for f in opzioni["funzioni"].split(",") if f.strip()]},
                             pacchetti.carica_privata(opzioni["chiave"]))
        testo = json.dumps(dati, ensure_ascii=False, indent=2)
        if opzioni.get("uscita"):
            with open(opzioni["uscita"], "w", encoding="utf-8") as f:
                f.write(testo)
            self.stdout.write(f"Licenza scritta in {opzioni['uscita']}")
        else:
            self.stdout.write(testo)
