from django.db import models


class AziendaMixin(models.Model):
    azienda = models.ForeignKey("core.Azienda", on_delete=models.PROTECT, verbose_name="azienda")

    class Meta:
        abstract = True
        indexes = [models.Index(fields=["azienda"])]


class ProprietaMixin(models.Model):
    """Campi personalizzati (CampoPersonalizzato) aggiunti dal cliente senza migrazioni: valori in JSON."""
    proprieta = models.JSONField("proprietà", default=dict, blank=True)

    class Meta:
        abstract = True
