from django.conf import settings
from django.db import models


class Personalizzazione(models.Model):
    """Attributi di una ModelView sovrascritti dal cliente (per tutte le aziende), con le versioni precedenti."""
    modulo = models.CharField("modulo", max_length=40)
    vista = models.CharField("vista", max_length=60)
    dati = models.JSONField("personalizzazione", default=dict, blank=True)
    storico = models.JSONField("versioni precedenti", default=list, blank=True)
    modificato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+", verbose_name="modificata da")
    modificato_il = models.DateTimeField("modificata il", auto_now=True)

    class Meta:
        verbose_name = "personalizzazione"
        verbose_name_plural = "personalizzazioni"
        ordering = ["modulo", "vista"]
        constraints = [models.UniqueConstraint(fields=["modulo", "vista"], name="studio_personalizzazione_unica")]

    def __str__(self):
        return f"{self.modulo}:{self.vista}"
