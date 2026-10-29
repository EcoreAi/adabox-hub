from django.core.management.base import BaseCommand

from ai import conoscenza
from ai.models import Frammento


class Command(BaseCommand):
    help = "Aggiorna l'indice della conoscenza dell'assistente (record, note, documenti) e i vettori mancanti"

    def add_arguments(self, parser):
        parser.add_argument("--fonte", choices=[f for f, _ in Frammento.FONTI], action="append",
                            help="solo questa fonte (ripetibile)")
        parser.add_argument("--secondi", type=int, default=3600, help="tempo massimo per i vettori")

    def handle(self, fonte, secondi, **_):
        conti = conoscenza.indicizza(fonte, limite_secondi=secondi)
        self.stdout.write(f"Frammenti nuovi {conti['nuovi']}, aggiornati {conti['aggiornati']}, tolti {conti['tolti']}, "
                          f"vettori calcolati {conti['vettori']}.")
        s = conoscenza.statistiche()
        self.stdout.write(f"Nell'indice: {s['frammenti']} frammenti, {s['con_vettore']} con vettore. "
                          f"Servizio: {s['servizio']}.")
