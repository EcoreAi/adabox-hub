"""Impacchetta e firma i moduli di addons/ e li mette in vendita sul portale."""
import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.registry import modules, pacchetti
from rivendita import servizi
from rivendita.models import Istanza


class Command(BaseCommand):
    help = "Pubblica sul portale i moduli di addons/ (impacchetta, firma con MODULI_CHIAVE_PRIVATA, registra)"

    def add_arguments(self, parser):
        parser.add_argument("slugs", nargs="*")
        parser.add_argument("--per", default="", help="assegna i moduli a questa istanza: cliente o codice")
        parser.add_argument("--tutti", action="store_true", help="tutti i moduli in addons/, tranne il portale stesso")

    def _istanza(self, valore):
        import uuid
        try:
            uuid.UUID(valore)
            trovate = list(Istanza.objects.filter(codice=valore))
        except ValueError:
            trovate = list(Istanza.objects.filter(cliente=valore))
        if len(trovate) != 1:
            raise CommandError(f"«{valore}»: {len(trovate)} istanze trovate, ne serve una. Usa il codice.")
        return trovate[0]

    def handle(self, slugs, tutti, per, **_):
        destinataria = self._istanza(per) if per else None   # prima di pubblicare: un nome sbagliato non lascia nulla a metà
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
            self.stdout.write(f"{slug} {p.versione}: pubblicato" + (" su misura" if p.modulo.su_misura else ""))
            if destinataria:
                destinataria.moduli_extra.add(p.modulo)
                self.stdout.write(f"{slug}: assegnato a {destinataria.cliente}")
        self.stdout.write(self.style.SUCCESS(f"Pubblicati {len(scelti)} moduli."))
