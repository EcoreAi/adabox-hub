"""Uso interno di `modulo`: gira in un processo nuovo, che ha già i moduli in INSTALLED_APPS."""
import importlib
import sys
import traceback
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import Modulo
from core.registry import manifest as mf
from core.registry.groups import crea_gruppi


def carica_fixture(manifest, demo=False):
    """loaddata delle fixture `data` (e `demo` se richiesto), con i percorsi assoluti."""
    file = list(manifest.data) + (list(manifest.demo) if demo else [])
    if file:
        call_command("loaddata", *[str(Path(manifest.percorso) / f) for f in file], verbosity=1)


def esegui_hook(manifest, nome, modulo, *args):
    """Chiama <manifest.hooks>.<nome>(modulo, *args) se il modulo hooks e la funzione esistono."""
    if not manifest.hooks:
        return False
    funzione = getattr(importlib.import_module(manifest.hooks), nome, None)
    if funzione is None:
        return False
    funzione(modulo, *args)
    return True


def aggiorna_riga(manifest, **campi):
    riga, _ = Modulo.objects.update_or_create(slug=manifest.slug, defaults={
        "nome": manifest.name, "versione_disponibile": manifest.version,
        "application": manifest.application, "ultimo_errore": "", **campi})
    return riga


def _ha_migrazioni(slug):
    return (Path(apps.get_app_config(slug).path) / "migrations" / "__init__.py").is_file()


def _manifest(slug):
    return mf.leggi(Path(settings.ADDONS_DIR) / slug)


class Command(BaseCommand):
    help = "uso interno di modulo: applica installazione, aggiornamento o disinstallazione"

    def add_arguments(self, parser):
        parser.add_argument("operazione", choices=["installa", "aggiorna", "disinstalla"])
        parser.add_argument("slugs", nargs="+")
        parser.add_argument("--demo", action="store_true")
        parser.add_argument("--elimina-dati", action="store_true")

    def handle(self, operazione, slugs, demo, elimina_dati, **_):
        try:
            for slug in slugs:
                self.stdout.write(f"--- {operazione} {slug}")
                getattr(self, f"_{operazione}")(slug, demo=demo, elimina_dati=elimina_dati)
            if not settings.DEBUG:
                call_command("collectstatic", interactive=False, verbosity=0)
        except Exception:
            self.stderr.write(traceback.format_exc())
            sys.exit(1)

    def _migra(self, slug, *destinazione):
        if _ha_migrazioni(slug):
            call_command("migrate", slug, *destinazione, interactive=False, verbosity=1)

    def _installa(self, slug, demo, **_):
        m = _manifest(slug)
        self._migra(slug)
        with transaction.atomic():
            carica_fixture(m, demo)
            gruppi = crea_gruppi(m)
            riga = aggiorna_riga(m)
            esegui_hook(m, "post_install", riga)
            aggiorna_riga(m, stato=Modulo.INSTALLATO, versione_installata=m.version,
                          installato_il=timezone.now(), gruppi_creati=gruppi)

    def _aggiorna(self, slug, **_):
        m = _manifest(slug)
        riga = Modulo.objects.filter(slug=slug).first()
        da = riga.versione_installata if riga else ""
        self._migra(slug)
        with transaction.atomic():
            carica_fixture(m)
            gruppi = crea_gruppi(m)
            riga = aggiorna_riga(m)
            esegui_hook(m, "post_upgrade", riga, da)
            aggiorna_riga(m, stato=Modulo.INSTALLATO, versione_installata=m.version,
                          aggiornato_il=timezone.now(), gruppi_creati=gruppi)

    def _disinstalla(self, slug, elimina_dati, **_):
        try:
            m = _manifest(slug)
        except mf.ManifestNonValido:
            m = None                                # modulo mancante: si toglie solo lo stato
        riga = Modulo.objects.filter(slug=slug).first()
        with transaction.atomic():
            if m:
                esegui_hook(m, "pre_uninstall", riga)
            if riga:
                Group.objects.filter(name__in=riga.gruppi_creati).delete()
        if elimina_dati and m and apps.is_installed(slug):
            self._migra(slug, "zero")
        Modulo.objects.filter(slug=slug).update(stato=Modulo.DISPONIBILE, versione_installata="",
                                                gruppi_creati=[], ultimo_errore="")
