from django.conf import settings
from django.db import models


class Conversazione(models.Model):
    """Una chat con l'assistente: personale, la vede solo chi l'ha aperta."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversazioni",
                               verbose_name="utente")
    titolo = models.CharField("titolo", max_length=120, default="Nuova chat")
    preferita = models.BooleanField("preferita", default=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)
    aggiornata = models.DateTimeField("aggiornata il", auto_now=True)

    class Meta:
        verbose_name = "conversazione"
        verbose_name_plural = "conversazioni"
        ordering = ["-aggiornata", "-pk"]

    def __str__(self):
        return self.titolo


class MessaggioChat(models.Model):
    UTENTE, ASSISTENTE = "utente", "assistente"
    conversazione = models.ForeignKey(Conversazione, on_delete=models.CASCADE, related_name="messaggi",
                                      verbose_name="conversazione")
    ruolo = models.CharField("ruolo", max_length=10, choices=[(UTENTE, "Utente"), (ASSISTENTE, "Assistente")])
    testo = models.TextField("testo")
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta:
        verbose_name = "messaggio"
        verbose_name_plural = "messaggi"
        ordering = ["creato", "pk"]

    def __str__(self):
        return f"{self.get_ruolo_display()}: {self.testo[:40]}"
