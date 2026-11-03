from django.conf import settings
from django.db import models


class Domanda(models.Model):
    """Una domanda fatta da una pagina: resta per capire che cosa chiede la gente, e dove."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="domande_ada", verbose_name="utente")
    url = models.CharField("pagina", max_length=300)
    titolo = models.CharField("titolo della pagina", max_length=200, blank=True)
    testo = models.TextField("domanda")
    conversazione = models.ForeignKey("ai.Conversazione", on_delete=models.SET_NULL, null=True, blank=True, related_name="domande_ada",
                                      verbose_name="conversazione")
    creata = models.DateTimeField("fatta il", auto_now_add=True)

    class Meta:
        verbose_name = "domanda"
        verbose_name_plural = "domande"
        ordering = ["-creata"]

    def __str__(self):
        return self.testo[:60]
