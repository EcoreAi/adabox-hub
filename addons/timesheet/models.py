from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.mixins import AziendaMixin


class RigaOre(AziendaMixin):
    data = models.DateField("data", default=timezone.localdate)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                               related_name="ore", verbose_name="utente")
    progetto = models.ForeignKey("progetti.Progetto", on_delete=models.PROTECT, related_name="ore",
                                 verbose_name="progetto")
    compito = models.ForeignKey("progetti.Compito", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="ore", verbose_name="compito")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    ore = models.DecimalField("ore", max_digits=5, decimal_places=2,
                              validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(24)])
    fatturabile = models.BooleanField("fatturabile", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "riga ore"
        verbose_name_plural = "ore"
        ordering = ["-data", "-pk"]
        permissions = [("vedi_tutte_ore", "Può vedere e registrare le ore di tutti")]

    def __str__(self):
        return f"{self.data:%d/%m/%Y} · {self.ore} h · {self.progetto}"

    def clean(self):
        errori = {}
        if self.compito_id and self.progetto_id and self.compito.progetto_id != self.progetto_id:
            errori["compito"] = "Il compito non appartiene al progetto scelto."
        if self.utente_id and self.data and self.ore:
            altre = (RigaOre.objects.filter(utente_id=self.utente_id, data=self.data).exclude(pk=self.pk)
                     .aggregate(t=Sum("ore"))["t"] or 0)
            if altre + self.ore > 24:
                errori["ore"] = f"Con questa riga le ore del {self.data:%d/%m/%Y} superano 24 (già registrate {altre})."
        if errori:
            raise ValidationError(errori)
