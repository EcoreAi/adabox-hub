from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin


class CostoOrario(AziendaMixin):
    """Quanto costa all'azienda un'ora di una persona, da una certa data: la storia serve per i margini passati."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="costi_orari", verbose_name="persona")
    costo = models.DecimalField("costo orario (€)", max_digits=8, decimal_places=2)
    dal = models.DateField("in vigore dal", default=timezone.localdate)

    class Meta(AziendaMixin.Meta):
        verbose_name = "costo orario"
        verbose_name_plural = "costi orari"
        ordering = ["utente__username", "-dal"]
        constraints = [models.UniqueConstraint(fields=["azienda", "utente", "dal"], name="commesse_costo_unico")]

    def __str__(self):
        return f"{self.utente}: {self.costo} €/h dal {self.dal:%d/%m/%Y}"


class Condizioni(AziendaMixin):
    """Come si fattura un progetto."""
    ORE, CORPO, NESSUNA = "ore", "corpo", "nessuna"
    TIPI = [(ORE, "A ore"), (CORPO, "A corpo"), (NESSUNA, "Non si fattura")]
    progetto = models.OneToOneField("progetti.Progetto", on_delete=models.CASCADE, related_name="condizioni", verbose_name="progetto")
    tipo = models.CharField("fatturazione", max_length=8, choices=TIPI, default=ORE)
    tariffa = models.DecimalField("tariffa oraria (€)", max_digits=8, decimal_places=2, default=0,
                                  help_text="vale per chi non ha una tariffa propria qui sotto")
    importo_corpo = models.DecimalField("importo a corpo (€)", max_digits=12, decimal_places=2, default=0)
    termine_pagamento = models.ForeignKey("fiscale.TerminePagamento", on_delete=models.SET_NULL, null=True, blank=True,
                                          verbose_name="pagamento")
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, null=True, blank=True, verbose_name="IVA",
                                 help_text="vuota = 22%")

    class Meta(AziendaMixin.Meta):
        verbose_name = "condizioni di un progetto"
        verbose_name_plural = "condizioni dei progetti"
        ordering = ["progetto__nome"]

    def __str__(self):
        return f"{self.progetto}: {self.get_tipo_display().lower()}"

    def clean(self):
        if self.tariffa is not None and self.tariffa < 0:
            raise ValidationError({"tariffa": "La tariffa non può essere negativa."})


class TariffaPersona(models.Model):
    condizioni = models.ForeignKey(Condizioni, on_delete=models.CASCADE, related_name="tariffe", verbose_name="condizioni")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+", verbose_name="persona")
    tariffa = models.DecimalField("tariffa oraria (€)", max_digits=8, decimal_places=2)

    class Meta:
        verbose_name = "tariffa di una persona"
        verbose_name_plural = "tariffe delle persone"
        constraints = [models.UniqueConstraint(fields=["condizioni", "utente"], name="commesse_tariffa_unica")]

    def __str__(self):
        return f"{self.utente}: {self.tariffa} €/h"


class OreTicket(models.Model):
    """Ore lavorate su un ticket, e il contratto dal cui monte ore si scalano."""
    riga = models.OneToOneField("timesheet.RigaOre", on_delete=models.CASCADE, related_name="su_ticket", verbose_name="ore")
    ticket = models.ForeignKey("helpdesk.Ticket", on_delete=models.CASCADE, related_name="ore_lavorate", verbose_name="ticket")
    contratto = models.ForeignKey("assistenza.Contratto", on_delete=models.SET_NULL, null=True, blank=True, related_name="ore_ticket",
                                  verbose_name="contratto")

    class Meta:
        verbose_name = "ore su un ticket"
        verbose_name_plural = "ore sui ticket"

    def __str__(self):
        return f"{self.riga} su {self.ticket.numero}"


class OreFatturate(models.Model):
    """Una riga di ore finita in una fattura. Se la fattura si annulla o si storna, torna da fatturare."""
    riga = models.OneToOneField("timesheet.RigaOre", on_delete=models.CASCADE, related_name="fatturazione", verbose_name="ore")
    fattura = models.ForeignKey("fatturazione.Fattura", on_delete=models.CASCADE, related_name="ore_fatturate", verbose_name="fattura")
    ore = models.DecimalField("ore fatturate", max_digits=5, decimal_places=2, default=Decimal(0))

    class Meta:
        verbose_name = "ore fatturate"
        verbose_name_plural = "ore fatturate"


class FatturaProgetto(models.Model):
    """Una fattura che conta tra i ricavi di un progetto."""
    fattura = models.OneToOneField("fatturazione.Fattura", on_delete=models.CASCADE, related_name="su_progetto", verbose_name="fattura")
    progetto = models.ForeignKey("progetti.Progetto", on_delete=models.CASCADE, related_name="fatture_commessa", verbose_name="progetto")

    class Meta:
        verbose_name = "fattura di un progetto"
        verbose_name_plural = "fatture dei progetti"
