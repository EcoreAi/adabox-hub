"""Prima di avviare il servizio (deploy/entrypoint.sh): si ferma se la configurazione non è sicura."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Controlli prima dell'avvio: fuori dal debug serve una SECRET_KEY propria."
    requires_system_checks = []

    def handle(self, *args, **opzioni):
        if not settings.DEBUG and settings.SECRET_KEY == settings.CHIAVE_DI_SVILUPPO:
            raise CommandError(
                "SECRET_KEY non è impostata: resta quella di sviluppo, nota a tutti. Con quella si firmano le sessioni e "
                "si cifrano le chiavi API salvate nel database. Mettine una casuale nel file .env (README) e riavvia.")
        self.stdout.write("Avvio: configurazione a posto.")
