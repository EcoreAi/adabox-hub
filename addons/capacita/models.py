from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.mixins import AziendaMixin

ORE_GIORNO, QUOTA = Decimal(8), 80         # per chi non ha una scheda


class Capacita(AziendaMixin):
    """Quante ore al giorno una persona dedica ai compiti: il resto se ne va in riunioni, assistenza, imprevisti."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="capacita", verbose_name="persona")
    ore_giorno = models.DecimalField("ore lavorate al giorno", max_digits=4, decimal_places=2, default=ORE_GIORNO,
                                     validators=[MinValueValidator(0), MaxValueValidator(24)])
    quota = models.PositiveSmallIntegerField("quota per i compiti (%)", default=QUOTA, validators=[MaxValueValidator(100)],
                                             help_text="la parte della giornata che resta per i compiti")
    sabato = models.BooleanField("lavora il sabato", default=False)
    domenica = models.BooleanField("lavora la domenica", default=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "capacità"
        verbose_name_plural = "capacità delle persone"
        ordering = ["utente__username"]
        constraints = [models.UniqueConstraint(fields=["azienda", "utente"], name="capacita_persona_unica")]

    def __str__(self):
        return f"{self.utente}: {self.ore_giorno} h × {self.quota}%"

    @property
    def ore_utili(self):
        return self.ore_giorno * self.quota / 100
