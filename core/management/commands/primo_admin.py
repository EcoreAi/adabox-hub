"""Il primo amministratore di un'istanza nuova, per deploy/flotta.py: ruolo Admin, password casuale, che stampa una volta.
Se esiste già un utente non fa nulla: rilanciarlo non cambia password a nessuno."""
import secrets

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from core import ruoli
from core.models import Azienda, Ruolo


class Command(BaseCommand):
    help = "Crea il primo admin di un'istanza nuova"

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--azienda", default="", help="nome dell'azienda iniziale")

    @transaction.atomic
    def handle(self, email, azienda, **_):
        if User.objects.filter(is_active=True).exclude(username__in=("assistente", "ada")).exists():
            self.stdout.write("Esiste già un utente: nessuna modifica.")
            return
        prima = Azienda.objects.order_by("pk").first()
        if prima is None:
            prima = Azienda.objects.create(nome=azienda or "Azienda")
        elif azienda:
            Azienda.objects.filter(pk=prima.pk).update(nome=azienda)
        password = secrets.token_urlsafe(14)
        utente = User.objects.create_user(email, email, password)
        profilo = utente.profilo
        profilo.aziende.set([prima])
        profilo.azienda_predefinita = prima
        profilo.ruolo = Ruolo.objects.get(nome="Admin")
        profilo.save()
        ruoli.applica(utente)
        self.stdout.write(f"PASSWORD={password}")
