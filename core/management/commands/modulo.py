from django.core.management.base import BaseCommand, CommandError

from core.registry import manifest, modules


class Command(BaseCommand):
    help = "Gestione dei moduli in addons/: lista, verifica, sincronizza"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="sottocomando", required=True)
        sub.add_parser("lista", help="moduli su disco e installati, con versione e stato")
        sub.add_parser("sincronizza", help="allinea le righe Modulo al disco e al file di stato")
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

    def _lista(self, **_):
        righe = modules.sincronizza()
        self.stdout.write(f"{'SLUG':<24}{'INSTALLATA':<12}{'DISPONIBILE':<13}{'STATO':<15}NOME")
        for r in righe:
            self.stdout.write(f"{r.slug:<24}{r.versione_installata or '—':<12}{r.versione_disponibile or '—':<13}"
                              f"{r.stato:<15}{r.nome}")

    def _sincronizza(self, **_):
        righe = modules.sincronizza()
        self.stdout.write(f"Sincronizzati {len(righe)} moduli.")
