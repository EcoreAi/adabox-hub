from django.core.management.base import BaseCommand, CommandError

from core.registry import manifest


class Command(BaseCommand):
    help = "Gestione dei moduli in addons/: verifica"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="sottocomando", required=True)
        p = sub.add_parser("verifica", help="valida il manifest di una cartella")
        p.add_argument("percorso")

    def handle(self, *args, sottocomando, **opzioni):
        getattr(self, f"_{sottocomando}")(**opzioni)

    def _verifica(self, percorso, **_):
        try:
            m = manifest.leggi(percorso)
        except manifest.ManifestNonValido as e:
            raise CommandError("manifest non valido:\n" + "\n".join(f"- {err}" for err in e.errori))
        self.stdout.write(f"OK {m.slug} {m.version}")
