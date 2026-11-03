from django.conf import settings
from django.db import models


class Preferenza(models.Model):
    """Com'è andata l'ultima volta e se la scheda deve aprirsi da sola: una riga per utente."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="riepilogo", verbose_name="utente")
    mostra_al_login = models.BooleanField("apri da solo all'accesso", default=True)
    accesso_precedente = models.DateTimeField("accesso precedente", null=True, blank=True, editable=False)
    ultimo_accesso = models.DateTimeField("ultimo accesso", null=True, blank=True, editable=False)
    aperto_il = models.DateTimeField("riepilogo aperto il", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "preferenza del riepilogo"
        verbose_name_plural = "preferenze del riepilogo"

    def __str__(self):
        return f"riepilogo di {self.utente}"
