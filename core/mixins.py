from django.db import models


class AziendaMixin(models.Model):
    azienda = models.ForeignKey("core.Azienda", on_delete=models.PROTECT, verbose_name="azienda")

    class Meta:
        abstract = True
        indexes = [models.Index(fields=["azienda"])]
