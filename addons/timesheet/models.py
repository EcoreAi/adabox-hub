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
    approvata = models.BooleanField("approvata", default=False, editable=False)
    approvata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
                                     related_name="+", verbose_name="approvata da")
    approvata_il = models.DateTimeField("approvata il", null=True, blank=True, editable=False)
    bloccata = models.BooleanField("già fatturata", default=False, editable=False,
                                   help_text="in una fattura: non si cambia finché la fattura è valida")

    class Meta(AziendaMixin.Meta):
        verbose_name = "riga ore"
        verbose_name_plural = "ore"
        ordering = ["-data", "-pk"]
        permissions = [("vedi_tutte_ore", "Può vedere e registrare le ore di tutti"),
                       ("approva_ore", "Può approvare e riaprire le ore")]

    def __str__(self):
        return f"{self.data:%d/%m/%Y} · {self.ore} h · {self.progetto}"

    @property
    def modificabile(self):
        return not (self.approvata or self.bloccata)

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


class Cronometro(AziendaMixin):
    """Il lavoro in corso di un utente: uno solo per volta, alla fine diventa una riga di ore."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cronometro",
                                  verbose_name="utente")
    progetto = models.ForeignKey("progetti.Progetto", on_delete=models.CASCADE, related_name="+", verbose_name="progetto")
    compito = models.ForeignKey("progetti.Compito", on_delete=models.CASCADE, null=True, blank=True, related_name="+",
                                verbose_name="compito")
    ticket_id_origine = models.PositiveBigIntegerField("ticket", null=True, blank=True, editable=False)
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    avviato = models.DateTimeField("avviato", default=timezone.now)

    class Meta(AziendaMixin.Meta):
        verbose_name = "cronometro"
        verbose_name_plural = "cronometri"

    def __str__(self):
        return f"{self.utente} · {self.progetto}"

    @property
    def etichetta(self):
        return self.compito.titolo if self.compito_id else (self.descrizione or self.progetto.nome)
