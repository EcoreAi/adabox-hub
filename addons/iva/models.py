from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.mixins import AziendaMixin


class Liquidazione(AziendaMixin):
    """Una liquidazione di periodo. Finché è aperta si ricalcola dai registri; chiusa, i numeri restano fermi
    (servono al periodo dopo e alla LIPE) anche se poi un registro cambia."""
    MENSILE, TRIMESTRALE = "M", "T"
    METODI_ACCONTO = [(1, "1 · Storico"), (2, "2 · Previsionale"), (3, "3 · Analitico"), (4, "4 · Soggetti particolari")]
    anno = models.PositiveIntegerField("anno")
    periodicita = models.CharField("periodicità", max_length=1, choices=[(MENSILE, "Mensile"), (TRIMESTRALE, "Trimestrale")])
    periodo = models.PositiveSmallIntegerField("periodo", help_text="mese (1-12) o trimestre (1-4)")
    credito_anno_precedente = models.DecimalField("credito dell'anno prima usato", max_digits=14, decimal_places=2, default=0,
                                                  validators=[MinValueValidator(0)])
    versamenti_auto = models.DecimalField("versamenti auto UE", max_digits=14, decimal_places=2, default=0,
                                          validators=[MinValueValidator(0)])
    crediti_imposta = models.DecimalField("crediti d'imposta usati", max_digits=14, decimal_places=2, default=0,
                                          validators=[MinValueValidator(0)])
    acconto = models.DecimalField("acconto di dicembre versato", max_digits=14, decimal_places=2, default=0,
                                  validators=[MinValueValidator(0)])
    metodo_acconto = models.PositiveSmallIntegerField("metodo dell'acconto", choices=METODI_ACCONTO, null=True, blank=True)
    chiusa = models.BooleanField("chiusa", default=False)
    dati = models.JSONField("numeri alla chiusura", default=dict, blank=True, editable=False)
    chiusa_il = models.DateTimeField("chiusa il", null=True, blank=True, editable=False)
    chiusa_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="chiusa da", editable=False)
    versata_il = models.DateField("versata il", null=True, blank=True)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "liquidazione IVA"
        verbose_name_plural = "liquidazioni IVA"
        ordering = ["-anno", "-periodo"]
        constraints = [models.UniqueConstraint(fields=["azienda", "anno", "periodicita", "periodo"], name="iva_liquidazione_unica")]

    def __str__(self):
        from .calcolo import nome_periodo
        return f"Liquidazione IVA {nome_periodo(self.periodicita, self.periodo)} {self.anno}"

    def clean(self):
        if self.acconto and self.acconto < Decimal("103.29"):
            raise ValidationError({"acconto": "L'acconto si versa solo da 103,29 € in su."})
        if self.acconto and not self.metodo_acconto:
            raise ValidationError({"metodo_acconto": "Indica con quale metodo hai calcolato l'acconto."})
        ultimo = 12 if self.periodicita == self.MENSILE else 4
        if self.acconto and self.periodo != ultimo:
            raise ValidationError({"acconto": "L'acconto entra solo nell'ultimo periodo dell'anno."})


class Detraibilita(models.Model):
    """Quanta IVA di una fattura ricevuta si può detrarre (auto 40%, telefoni 50%, spese di rappresentanza 0%...)."""
    fattura = models.OneToOneField("sdi.FatturaPassiva", on_delete=models.CASCADE, related_name="detraibilita",
                                   verbose_name="fattura")
    percentuale = models.DecimalField("IVA detraibile %", max_digits=5, decimal_places=2, default=100,
                                      validators=[MinValueValidator(0), MaxValueValidator(100)])
    motivo = models.CharField("motivo", max_length=120, blank=True, help_text="es. auto aziendale, art. 19-bis1")

    class Meta:
        verbose_name = "detraibilità"
        verbose_name_plural = "detraibilità"

    def __str__(self):
        return f"{self.fattura}: {self.percentuale:g}%"
