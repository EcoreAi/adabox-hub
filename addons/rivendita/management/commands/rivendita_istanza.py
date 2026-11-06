"""Le istanze del portale da riga di comando, per deploy/flotta.py. Stampa una riga JSON: il token si vede solo qui."""
import datetime
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.registry import pacchetti
from rivendita.models import Istanza, ModuloVendibile, Piano


class Command(BaseCommand):
    help = "Crea o revoca un'istanza del portale"

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="azione", required=True)
        p = sub.add_parser("crea")
        p.add_argument("--cliente", required=True)
        p.add_argument("--email", default="")
        p.add_argument("--piano", required=True)
        p.add_argument("--url", default="")
        p.add_argument("--scadenza", required=True, help="AAAA-MM-GG")
        p.add_argument("--moduli", nargs="*", default=[])
        p = sub.add_parser("revoca")
        p.add_argument("--codice", required=True)

    def handle(self, azione, **o):
        getattr(self, f"_{azione}")(**o)

    def _crea(self, cliente, email, piano, url, scadenza, moduli, **_):
        scelto = Piano.objects.filter(nome=piano, attivo=True).first()
        if scelto is None:
            raise CommandError(f"piano «{piano}» inesistente o spento. Quelli attivi: {', '.join(Piano.objects.filter(attivo=True).values_list('nome', flat=True))}")
        try:
            data = datetime.date.fromisoformat(scadenza)
        except ValueError as e:
            raise CommandError("scadenza non valida: AAAA-MM-GG") from e
        extra = list(ModuloVendibile.objects.filter(slug__in=moduli))
        if mancanti := set(moduli) - {m.slug for m in extra}:
            raise CommandError(f"moduli non in vendita: {', '.join(sorted(mancanti))}")
        if not settings.MODULI_CHIAVE_PRIVATA:
            raise CommandError("manca MODULI_CHIAVE_PRIVATA: il portale non può firmare licenze")
        istanza = Istanza.objects.create(cliente=cliente, email=email, piano=scelto, url=url, scadenza=data, ospitata=True)
        istanza.moduli_extra.set(extra)
        pubblica = pacchetti.pubblica_b64(pacchetti.carica_privata(settings.MODULI_CHIAVE_PRIVATA))
        self.stdout.write(json.dumps({"codice": str(istanza.codice), "token": istanza.nuovo_token(), "chiave_pubblica": pubblica}))

    def _revoca(self, codice, **_):
        trovate = Istanza.objects.filter(codice=codice).update(attiva=False, token_hash="")
        if not trovate:
            raise CommandError("istanza non trovata")
        self.stdout.write(json.dumps({"revocata": codice}))
