"""Istanza di prova per chi integra (SANDBOX=True nell'ambiente): «sandbox prepara» genera i dati dimostrativi, crea
l'utente «integrazione» con il ruolo di responsabile su tutti i moduli e un token API a scadenza, e stampa gli indirizzi
utili; «sandbox azzera» rimette i dati demo da capo (il token resta). Rifiuta di girare su un'istanza vera."""
import datetime

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

UTENTE = "integrazione"


class Command(BaseCommand):
    help = "Istanza di prova per chi integra: «prepara» (dati demo, utente e token) o «azzera» (dati demo da capo)."

    def add_arguments(self, parser):
        parser.add_argument("operazione", choices=["prepara", "azzera"])
        parser.add_argument("--giorni", type=int, default=90, help="validità del token (default 90 giorni)")
        parser.add_argument("--email", default="", help="email di chi integra (per l'utente)")

    def handle(self, operazione, giorni, email, **_):
        if not getattr(settings, "SANDBOX", False):
            raise CommandError("Questa non è un'istanza di prova: imposta SANDBOX=True nell'ambiente. I dati demo non vanno "
                               "mai in un'istanza con dati veri.")
        from core.models import Azienda, ProfiloUtente, Ruolo, TokenApi
        if operazione == "azzera":
            try:
                call_command("dati_demo", "azzera", stdout=self.stdout)
            except CommandError:
                pass                                         # niente da togliere
            call_command("dati_demo", "genera", stdout=self.stdout)
            self.stdout.write(self.style.SUCCESS("Dati demo rigenerati."))
            return
        try:
            call_command("dati_demo", "genera", stdout=self.stdout)
        except CommandError as e:
            self.stdout.write(f"Dati demo: {e}")
        azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
        ruolo, _ = Ruolo.objects.get_or_create(nome="Integrazione", defaults={
            "descrizione": "Chi prova l'API nell'istanza di prova", "livello_base": "responsabile"})
        Utente = get_user_model()
        utente, nuovo = Utente.objects.get_or_create(username=UTENTE, defaults={"email": email, "first_name": "Integrazione"})
        if nuovo:
            utente.set_unusable_password()
            utente.save()
        profilo, _ = ProfiloUtente.objects.get_or_create(utente=utente)
        profilo.ruolo = ruolo
        profilo.save()
        if azienda is not None:
            profilo.aziende.add(azienda)
        from core import ruoli
        ruoli.applica(utente)
        scadenza = timezone.localdate() + datetime.timedelta(days=giorni)
        _, chiaro = TokenApi.genera(utente, f"sandbox {timezone.localdate():%d/%m/%Y}", scadenza=scadenza)
        base = settings.SITO_URL
        self.stdout.write(self.style.SUCCESS("Istanza di prova pronta."))
        self.stdout.write(f"  Token API (si vede solo ora, vale fino al {scadenza:%d/%m/%Y}): {chiaro}")
        self.stdout.write(f"  Documentazione: {base}/api/v1/docs  ·  schema: {base}/api/v1/openapi.json")
        self.stdout.write(f"  Client Python:  {base}/api/v1/sdk/python/")
        self.stdout.write(f"  Prova:          curl -H 'Authorization: Bearer <token>' {base}/api/v1/me/")
