"""Emette un file di licenza del modulo AI (da usare in ICHNOBYTE con la chiave privata dei pacchetti)."""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from core import funzioni
from core.registry import pacchetti

from ai import licenza


class Command(BaseCommand):
    help = "Genera un file di licenza firmato per il modulo AI"

    def add_arguments(self, parser):
        parser.add_argument("--chiave", required=True, help="chiave privata PEM di ICHNOBYTE")
        parser.add_argument("--cliente", required=True)
        parser.add_argument("--scadenza", required=True, help="AAAA-MM-GG")
        parser.add_argument("--utenti", type=int, default=0, help="utenti al mese (0 = senza limite)")
        parser.add_argument("--funzioni", help="chiavi del catalogo separate da virgola (default: tutte)")
        parser.add_argument("--formula", choices=sorted(licenza.FORMULE), help="come si vende l'assistente (default: propria, la chiave del cliente)")
        parser.add_argument("--quota-utente", help="$ al mese per utente sui provider forniti con il piano (con «inclusa»)")
        parser.add_argument("--quota-istanza", help="$ al mese per tutta l'istanza: quota compresa con «inclusa», tetto con «consumo»")
        parser.add_argument("--uscita", help="file da scrivere (default: stampa)")

    def _quota(self, nome, valore):
        from decimal import Decimal, InvalidOperation
        try:
            quota = Decimal(valore)
        except InvalidOperation as e:
            raise CommandError(f"--{nome.replace('_', '-')} non è un numero") from e
        if not quota.is_finite() or quota < 0:
            raise CommandError(f"--{nome.replace('_', '-')} deve essere zero o più")
        return str(quota)

    def handle(self, *args, **opzioni):
        try:
            datetime.date.fromisoformat(opzioni["scadenza"])
        except ValueError as e:
            raise CommandError("scadenza non valida (AAAA-MM-GG)") from e
        contenuto = {"cliente": opzioni["cliente"], "emessa": datetime.date.today().isoformat(),
                     "scadenza": opzioni["scadenza"], "utenti": opzioni["utenti"]}
        if opzioni.get("funzioni") is not None:
            chiavi = [f.strip() for f in opzioni["funzioni"].split(",") if f.strip()]
            catalogo = {f["chiave"] for f in funzioni.catalogo("ai")}
            if sconosciute := sorted(set(chiavi) - catalogo):
                raise CommandError(f"funzioni sconosciute: {', '.join(sconosciute)} (ammesse: {', '.join(sorted(catalogo))})")
            contenuto["funzioni"] = chiavi
        if opzioni.get("formula"):
            contenuto["formula"] = opzioni["formula"]
        for nome in ("quota_utente", "quota_istanza"):
            if opzioni.get(nome) is not None:
                contenuto[nome] = self._quota(nome, opzioni[nome])
        if licenza.termini(contenuto)["formula"] == licenza.PROPRIA and ("quota_utente" in contenuto or "quota_istanza" in contenuto):
            raise CommandError("le quote valgono con --formula inclusa o consumo")
        dati = licenza.firma(contenuto, pacchetti.carica_privata(opzioni["chiave"]))
        testo = json.dumps(dati, ensure_ascii=False, indent=2)
        if opzioni.get("uscita"):
            with open(opzioni["uscita"], "w", encoding="utf-8") as f:
                f.write(testo)
            self.stdout.write(f"Licenza scritta in {opzioni['uscita']}")
        else:
            self.stdout.write(testo)
