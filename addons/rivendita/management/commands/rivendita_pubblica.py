"""Impacchetta e firma i moduli di addons/ e li mette in vendita sul portale."""
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.registry import modules, pacchetti
from rivendita import servizi


class Command(BaseCommand):
    help = "Pubblica sul portale i moduli di addons/ (impacchetta, firma con MODULI_CHIAVE_PRIVATA, registra)"

    def add_arguments(self, parser):
        parser.add_argument("slugs", nargs="*")
        parser.add_argument("--tutti", action="store_true", help="tutti i moduli in addons/, tranne il portale stesso")

    def handle(self, slugs, tutti, **_):
        info = modules.scopri()
        scelti = [s for s in sorted(info) if s != "rivendita"] if tutti else slugs
        if not scelti:
            raise CommandError("Indica i moduli o --tutti.")
        privata = servizi.chiave_privata()
        for slug in scelti:
            if slug not in info or info[slug].manifest is None:
                raise CommandError(f"{slug} non è un modulo valido in {settings.ADDONS_DIR}")
            with tempfile.TemporaryDirectory() as uscita:
                p = servizi.pubblica(pacchetti.impacchetta(info[slug].cartella, uscita, privata))
            self.stdout.write(f"{slug} {p.versione}: pubblicato")
        self.stdout.write(self.style.SUCCESS(f"Pubblicati {len(scelti)} moduli."))
