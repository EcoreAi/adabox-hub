from django.core.management.base import BaseCommand, CommandError

from core.backup import BackupFallito
from core.registry import install, manifest, modules


class Command(BaseCommand):
    help = "Gestione dei moduli in addons/: lista, verifica, sincronizza, installa, aggiorna, disinstalla"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="sottocomando", required=True)
        sub.add_parser("lista", help="moduli su disco e installati, con versione e stato")
        sub.add_parser("sincronizza", help="allinea le righe Modulo al disco e al file di stato")
        p = sub.add_parser("installa", help="installa moduli e dipendenze mancanti")
        p.add_argument("slugs", nargs="+")
        p.add_argument("--demo", action="store_true", help="carica anche i dati dimostrativi")
        p.add_argument("--riavvia", action="store_true", help="ricarica il server a fine operazione")
        p.add_argument("--si", action="store_true", help="non chiedere conferma")
        p = sub.add_parser("aggiorna", help="aggiorna i moduli da aggiornare")
        p.add_argument("slugs", nargs="*")
        p.add_argument("--tutti", action="store_true")
        p.add_argument("--riavvia", action="store_true")
        p = sub.add_parser("disinstalla", help="disinstalla un modulo")
        p.add_argument("slug")
        p.add_argument("--elimina-dati", action="store_true", help="elimina anche le tabelle del modulo")
        p.add_argument("--riavvia", action="store_true")
        p.add_argument("--si", action="store_true", help="non chiedere conferma")
        p = sub.add_parser("verifica", help="valida il manifest di una cartella")
        p.add_argument("percorso")

    OPERAZIONI = {"installa", "aggiorna", "disinstalla"}

    def handle(self, *args, sottocomando, **opzioni):
        """Le operazioni chiudono con '== FINE ok ==' o '== FINE errore ==': la pagina Moduli
        legge il log del sottoprocesso e capisce così quando ha finito."""
        try:
            getattr(self, f"_{sottocomando}")(**opzioni)
        except (install.ErroreInstallazione, manifest.ManifestNonValido, BackupFallito) as e:
            self._fine(sottocomando, "errore", str(e))
            raise CommandError(str(e))
        except BaseException as e:
            self._fine(sottocomando, "errore", repr(e))
            raise
        self._fine(sottocomando, "ok")

    def _fine(self, sottocomando, esito, errore=""):
        if sottocomando in self.OPERAZIONI:
            if errore:
                self.stdout.write(f"ERRORE: {errore}")
            self.stdout.write(f"== FINE {esito} ==")
            self.stdout.flush()

    def _chiedi(self, domanda):
        self.stdout.write(f"{domanda} [s/N] ", ending="")
        self.stdout.flush()
        return input().strip().lower() in ("s", "si", "sì", "y")

    def _installa(self, slugs, demo, riavvia, si, **_):
        def conferma(extra):
            self.stdout.write("Verranno installate anche le dipendenze: " + ", ".join(extra))
            return si or self._chiedi("Procedere?")
        try:
            fatti = install.installa(slugs, demo=demo, riavvia=riavvia, conferma=conferma)
        finally:
            modules.sincronizza()
        self.stdout.write(f"Installati: {', '.join(fatti)}" if fatti else "Annullato.")

    def _aggiorna(self, slugs, tutti, riavvia, **_):
        if not slugs and not tutti:
            raise CommandError("indica gli slug da aggiornare oppure --tutti")
        try:
            fatti = install.aggiorna(slugs, tutti=tutti, riavvia=riavvia)
        finally:
            modules.sincronizza()
        self.stdout.write(f"Aggiornati: {', '.join(fatti)}")

    def _disinstalla(self, slug, elimina_dati, riavvia, si, **_):
        if elimina_dati and not si and not self._chiedi(f"Eliminare le tabelle e i dati di {slug}?"):
            self.stdout.write("Annullato.")
            return
        try:
            install.disinstalla(slug, elimina_dati=elimina_dati, riavvia=riavvia)
        finally:
            modules.sincronizza()
        self.stdout.write(f"Disinstallato: {slug}")

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
