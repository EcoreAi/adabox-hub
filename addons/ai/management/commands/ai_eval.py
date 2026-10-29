from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from ai import valutazione
from ai.models import Assistente
from core.models import Azienda


class Command(BaseCommand):
    help = "Valuta l'assistente con le domande d'oro (del file o di un assistente). Esce con 1 se qualcosa fallisce."

    def add_arguments(self, parser):
        parser.add_argument("--utente", help="username con cui rispondere (default: il primo superuser)")
        parser.add_argument("--assistente", help="nome dell'assistente: usa le sue domande d'oro e la sua configurazione")
        parser.add_argument("--file", help="file JSON delle domande (default: quello del modulo)")
        parser.add_argument("--copioni", action="store_true",
                            help="modello finto con i copioni delle domande (percorso degli strumenti, senza costi)")

    def handle(self, utente, assistente, file, copioni, **_):
        Utente = get_user_model()
        persona = (Utente.objects.filter(username=utente).first() if utente
                   else Utente.objects.filter(is_superuser=True, is_active=True).order_by("pk").first())
        if persona is None:
            raise CommandError("utente non trovato")
        scelto = None
        if assistente:
            scelto = Assistente.objects.filter(nome__iexact=assistente).first()
            if scelto is None:
                raise CommandError(f"assistente «{assistente}» non trovato")
        domande = scelto.domande_oro if scelto and not file else valutazione.carica(file)
        if not domande:
            raise CommandError("nessuna domanda d'oro")
        risultati = valutazione.valuta(domande, persona, Azienda.objects.order_by("pk").first(), scelto, copioni)
        for r in risultati:
            self.stdout.write(f"{'OK ' if r['ok'] else 'NO '} {r['domanda'][:70]:<70} {r['secondi']:>5}s "
                              f"{r['costo']:.4f}$  [{', '.join(r['strumenti']) or '-'}]")
            for p in r["problemi"]:
                self.stdout.write(f"      - {p}")
        riusciti = sum(r["ok"] for r in risultati)
        self.stdout.write(f"Riuscite {riusciti} su {len(risultati)}; costo {sum(r['costo'] for r in risultati):.4f} $.")
        if riusciti < len(risultati):
            raise SystemExit(1)
