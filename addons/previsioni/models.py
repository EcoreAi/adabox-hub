"""L'impostazione del servizio di previsione: dell'istanza, non di un'azienda."""
from django.db import models

from core import cifratura


class ServizioPrevisioni(models.Model):
    """Una sola riga: la chiave d'accesso al servizio, cifrata e mai mostrata. L'URL sta nelle impostazioni del modulo."""
    chiave_cifrata = models.TextField(blank=True, editable=False)

    class Meta:
        verbose_name = "servizio di previsione"
        verbose_name_plural = "servizio di previsione"

    @classmethod
    def corrente(cls):
        return cls.objects.order_by("pk").first() or cls.objects.create()

    @property
    def chiave(self):
        return cifratura.decifra(self.chiave_cifrata)

    def __str__(self):
        return "Servizio di previsione"
