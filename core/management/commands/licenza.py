"""Licenza dell'istanza a riga di comando: guardarla, firmarne una (senza portale), caricarla, sincronizzarsi col portale."""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import licenza
from core.registry import pacchetti, sincronia


class Command(BaseCommand):
    help = "Licenza dell'istanza"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="sottocomando", required=True)
        sub.add_parser("stato", help="che cosa dice la licenza presente")
        p = sub.add_parser("firma", help="crea un file di licenza (si fa da ICHNOBYTE, con la chiave privata)")
        p.add_argument("--firma", required=True, help="file della chiave privata")
        p.add_argument("--cliente", required=True)
        p.add_argument("--istanza", default="")
        p.add_argument("--piano", default="")
        p.add_argument("--moduli", required=True, help="slug separati da virgole, dipendenze comprese")
        p.add_argument("--utenti", type=int, default=0, help="tetto di utenti attivi (0 = senza tetto)")
        p.add_argument("--scadenza", required=True, help="AAAA-MM-GG")
        p.add_argument("--grazia", type=int, default=licenza.GRAZIA_PREDEFINITA, help="giorni dopo la scadenza prima della sola lettura")
        p.add_argument("--uscita", default="licenza.json")
        p = sub.add_parser("carica", help="carica un file di licenza su questa istanza")
        p.add_argument("file")
        sub.add_parser("sincronizza", help="chiede subito al portale licenza e moduli, e li applica")

    def handle(self, *args, sottocomando, **opzioni):
        getattr(self, f"_{sottocomando}")(**opzioni)

    def _stato(self, **_):
        s = licenza.attuale()
        self.stdout.write(f"obbligatoria: {'sì' if licenza.obbligatoria() else 'no'}")
        if not s.valida:
            self.stdout.write(s.motivo)
            return
        self.stdout.write(f"cliente: {s.cliente} · piano: {s.piano or '-'} · scadenza: {s.scadenza} · utenti: {s.utenti or 'senza tetto'}")
        self.stdout.write("moduli: " + ", ".join(sorted(s.moduli)))

    def _firma(self, firma, cliente, istanza, piano, moduli, utenti, scadenza, grazia, uscita, **_):
        file = licenza.firma({"cliente": cliente, "istanza": istanza, "piano": piano, "utenti": utenti, "scadenza": scadenza,
                              "grazia_giorni": grazia, "emessa": timezone.now().isoformat(timespec="seconds"),
                              "moduli": sorted(m.strip() for m in moduli.split(",") if m.strip())}, pacchetti.carica_privata(firma))
        Path(uscita).write_text(json.dumps(file, ensure_ascii=False, indent=1))
        self.stdout.write(self.style.SUCCESS(f"Licenza scritta in {uscita}"))

    def _carica(self, file, **_):
        try:
            s = licenza.salva(Path(file).read_text())
        except (OSError, ValueError) as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Licenza di {s.cliente} caricata, valida fino al {s.scadenza}."))

    def _sincronizza(self, **_):
        esito = sincronia.esegui()
        if esito is None:
            raise CommandError("Questa istanza non ha un portale: imposta LICENZA_PORTALE_URL e LICENZA_TOKEN.")
        for riga in esito["fatti"]:
            self.stdout.write(riga)
        if esito["errori"]:
            raise CommandError("; ".join(esito["errori"]))
        self.stdout.write(self.style.SUCCESS("Sincronizzata."))
