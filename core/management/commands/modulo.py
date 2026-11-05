from django.core.management.base import BaseCommand, CommandError

from core.backup import BackupFallito
from core.registry import install, manifest, modules


class Command(BaseCommand):
    help = "Gestione dei moduli in addons/: lista, verifica, sincronizza, installa, aggiorna, disinstalla"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="sottocomando", required=True)
        sub.add_parser("lista", help="moduli su disco e installati, con versione e stato")
        p = sub.add_parser("chiavi", help="genera una coppia di chiavi Ed25519 per firmare i pacchetti")
        p.add_argument("--uscita", default="chiave-moduli.pem", help="file della chiave privata (da custodire)")
        p = sub.add_parser("impacchetta", help="crea lo zip di un modulo (firmato con --firma)")
        p.add_argument("modulo", help="slug in addons/ o percorso della cartella")
        p.add_argument("--firma", help="file della chiave privata")
        p.add_argument("--uscita", default="dist", help="cartella dei pacchetti (default dist/)")
        p = sub.add_parser("nuovo", help="crea un modulo funzionante in addons/, da cui partire (non lo installa)")
        p.add_argument("slug")
        p.add_argument("--nome", default="", help="nome nel menu, es. «Bolle»")
        p.add_argument("--modello", default="", help="nome del primo modello, es. Bolla")
        p.add_argument("--dipende", nargs="*", default=[], help="moduli da cui dipende")
        p = sub.add_parser("controlla", help="controlla le regole di un modulo leggendone il codice")
        p.add_argument("modulo", nargs="?", help="slug in addons/ o percorso della cartella")
        p.add_argument("--tutti", action="store_true", help="tutti i moduli in addons/")
        p.add_argument("--solo-errori", action="store_true", help="senza gli avvisi")
        p = sub.add_parser("collauda", help="installazione vergine e test di moduli, in un'istanza usa e getta")
        p.add_argument("slugs", nargs="*")
        p.add_argument("--tutti", action="store_true", help="tutti i moduli in addons/")
        p = sub.add_parser("compatibilita", help="prova il modulo accanto a ciascuno degli altri e a tutti insieme, in istanze usa e getta")
        p.add_argument("slug")
        p.add_argument("--con", nargs="*", default=None, help="solo accanto a questi moduli")
        p.add_argument("--paralleli", type=int, default=4)
        p = sub.add_parser("sonda", help="uso interno di compatibilita: solo in un'istanza usa e getta")
        p.add_argument("slug")
        p = sub.add_parser("indice", help="crea il catalogo firmato (indice.json) dai pacchetti di una cartella")
        p.add_argument("cartella")
        p.add_argument("--firma", required=True, help="file della chiave privata")
        p.add_argument("--url-base", default="", help="URL da cui si scaricano i pacchetti (default: accanto all'indice)")
        p = sub.add_parser("carica", help="controlla un pacchetto zip e lo estrae in addons/ (non installa)")
        p.add_argument("pacchetto")
        p.add_argument("--forza", action="store_true", help="sostituisce anche la stessa versione")
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
        p = sub.add_parser("disattiva", help="spegne un modulo installato per tutti (resta installato con i dati)")
        p.add_argument("slug")
        p = sub.add_parser("riattiva", help="riaccende un modulo disattivato")
        p.add_argument("slug")
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

    def _nuovo(self, slug, nome, modello, dipende, **_):
        from core.registry import nuovo
        try:
            cartella = nuovo.crea(slug, nome, modello, dipende)
        except nuovo.NomeNonValido as e:
            raise CommandError(str(e))
        self.stdout.write(f"Creato {cartella}. Per provarlo: modulo installa {slug}. Prima di consegnarlo: modulo controlla {slug}, "
                          f"modulo collauda {slug}, modulo compatibilita {slug}. Guida: docs/guida-moduli.md")

    def _controlla(self, modulo, tutti, solo_errori, **_):
        from pathlib import Path

        from django.conf import settings

        from core.registry import controlli
        if tutti == bool(modulo):
            raise CommandError("indica un modulo oppure --tutti")
        cartelle = ([i.cartella for i in modules.scopri().values() if i.manifest is not None] if tutti else
                    [Path(modulo) if "/" in modulo else Path(settings.ADDONS_DIR) / modulo])
        errori = avvisi = 0
        for cartella in cartelle:
            if not Path(cartella).is_dir():
                raise CommandError(f"cartella {cartella} inesistente")
            for r in controlli.controlla(cartella):
                errori += r.livello == controlli.ERRORE
                avvisi += r.livello == controlli.AVVISO
                if r.livello == controlli.ERRORE or not solo_errori:
                    self.stdout.write(f"{Path(cartella).name}: {r}")
        self.stdout.write(f"Errori: {errori}, avvisi: {avvisi}.")
        if errori:
            raise CommandError("il controllo ha trovato errori da correggere")

    def _chiavi(self, uscita, **_):
        from pathlib import Path

        from core.registry import pacchetti
        destinazione = Path(uscita)
        if destinazione.exists():
            raise CommandError(f"{destinazione} esiste già: non la sovrascrivo")
        privata, pubblica = pacchetti.genera_chiavi()
        destinazione.write_bytes(privata)
        destinazione.chmod(0o600)
        self.stdout.write(f"Chiave privata: {destinazione} (custodiscila, non metterla nel repository)")
        self.stdout.write(f"Chiave pubblica (per MODULI_CHIAVI_FIDATE): {pubblica}")
        self.stdout.write(f"Impronta: {pacchetti.impronta(pubblica)}")

    def _impacchetta(self, modulo, firma, uscita, **_):
        from pathlib import Path

        from django.conf import settings

        from core.registry import pacchetti
        cartella = Path(modulo) if "/" in modulo else Path(settings.ADDONS_DIR) / modulo
        if not cartella.is_dir():
            raise CommandError(f"cartella {cartella} inesistente")
        privata = pacchetti.carica_privata(firma) if firma else None
        zip_ = pacchetti.impacchetta(cartella, uscita, privata)
        stato = f"firmato ({pacchetti.impronta(pacchetti.pubblica_b64(privata))})" if privata else "non firmato"
        self.stdout.write(f"Pacchetto {zip_} {stato}")

    def _collauda(self, slugs, tutti, **_):
        from core.registry import collaudo
        if not slugs and not tutti:
            raise CommandError("indica i moduli da collaudare oppure --tutti")
        try:
            ordine, info = collaudo.da_collaudare(None if tutti else slugs)
        except ValueError as e:
            raise CommandError(str(e))
        falliti = []
        for slug in ordine:
            self.stdout.write(f"Collaudo di {slug}…", ending=" ")
            self.stdout.flush()
            r = collaudo.collauda(slug, info)
            self.stdout.write(("OK" if r.ok else "KO") + "  " + " · ".join(f"{n} {'✓' if ok else '✗'}" for n, ok in r.passi))
            if not r.ok:
                falliti.append(slug)
                self.stdout.write(r.dettaglio)
        if falliti:
            raise CommandError(f"collaudo fallito: {', '.join(falliti)}")
        self.stdout.write(f"Collaudo riuscito: {', '.join(ordine)}")

    def _compatibilita(self, slug, con, paralleli, **_):
        from core.registry import collaudo
        try:
            esiti = collaudo.compatibilita(slug, con, paralleli)
        except ValueError as e:
            raise CommandError(str(e))
        falliti = [nome for nome, errore in esiti if errore]
        for nome, errore in esiti:
            self.stdout.write(f"{slug} + {nome}: {'KO' if errore else 'OK'}")
            if errore:
                self.stdout.write(errore)
        if falliti:
            raise CommandError(f"non compatibile con: {', '.join(falliti)}")
        self.stdout.write(f"Compatibile: {len(esiti)} combinazioni provate.")

    def _sonda(self, slug, **_):
        from django.conf import settings

        from core.registry import collaudo
        if "sqlite" not in str(settings.DATABASES["default"]["ENGINE"]) or not settings.DEBUG:
            raise CommandError("la sonda crea un utente: si usa solo nelle istanze usa e getta")
        if errori := collaudo.sonda(slug):
            raise CommandError("\n".join(errori))

    def _indice(self, cartella, firma, url_base, **_):
        from core.registry import pacchetti
        n = pacchetti.crea_indice(cartella, pacchetti.carica_privata(firma), url_base)
        self.stdout.write(f"Catalogo con {n} pacchetti firmati in {cartella}/indice.json (e indice.sig)")

    def _carica(self, pacchetto, forza, **_):
        from core.registry import pacchetti
        try:
            esito = pacchetti.carica(pacchetto, forza=forza)
        except pacchetti.PacchettoNonValido as e:
            raise CommandError("pacchetto rifiutato:\n" + "\n".join(f"- {err}" for err in e.errori))
        origine = f"firmato da {esito.firmato_da}" if esito.firmato_da else "non firmato"
        self.stdout.write(f"Caricato {esito.slug} {esito.versione} ({origine}). Installalo o aggiornalo da /moduli/ "
                          f"o con `modulo installa {esito.slug}`.")
        for avviso in esito.avvisi:
            self.stdout.write(f"Avviso: {avviso}")

    def _lista(self, **_):
        righe = modules.sincronizza()
        self.stdout.write(f"{'SLUG':<24}{'INSTALLATA':<12}{'DISPONIBILE':<13}{'STATO':<15}NOME")
        for r in righe:
            self.stdout.write(f"{r.slug:<24}{r.versione_installata or '—':<12}{r.versione_disponibile or '—':<13}"
                              f"{r.stato:<15}{r.nome}")

    def _sincronizza(self, **_):
        righe = modules.sincronizza()
        self.stdout.write(f"Sincronizzati {len(righe)} moduli.")

    def _disattiva(self, slug, **_):
        self._attivazione(slug, False)

    def _riattiva(self, slug, **_):
        self._attivazione(slug, True)

    def _attivazione(self, slug, attivo):
        if not modules.imposta_attivo(slug, attivo):
            raise install.NonInstallato(f"{slug} non è installato")
        self.stdout.write(f"{slug} {'riattivato' if attivo else 'disattivato'}.")
