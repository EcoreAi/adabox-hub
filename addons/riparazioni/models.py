"""Garanzie e riparazioni."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin


class GaranziaProdotto(AziendaMixin):
    """Quanto dura la garanzia di un prodotto verso il cliente, e quella del fornitore verso di noi (per il recupero)."""
    prodotto = models.OneToOneField("prodotti.Prodotto", on_delete=models.CASCADE, related_name="garanzia", verbose_name="prodotto")
    mesi = models.PositiveSmallIntegerField("mesi di garanzia al cliente", default=24)
    mesi_fornitore = models.PositiveSmallIntegerField("mesi di garanzia del fornitore", null=True, blank=True)
    condizioni = models.TextField("condizioni", blank=True, help_text="che cosa copre e che cosa no")

    class Meta(AziendaMixin.Meta):
        verbose_name = "garanzia del prodotto"
        verbose_name_plural = "garanzie dei prodotti"

    def __str__(self):
        return f"{self.prodotto}: {self.mesi} mesi"


class Riparazione(AziendaMixin):
    RICEVUTA, PREVENTIVO, APPROVATA, LAVORAZIONE, PRONTA, RICONSEGNATA, RIFIUTATA = (
        "ricevuta", "preventivo", "approvata", "lavorazione", "pronta", "riconsegnata", "rifiutata")
    STATI = [(RICEVUTA, "Ricevuta"), (PREVENTIVO, "Preventivo inviato"), (APPROVATA, "Approvata"), (LAVORAZIONE, "In lavorazione"),
             (PRONTA, "Pronta"), (RICONSEGNATA, "Riconsegnata"), (RIFIUTATA, "Preventivo rifiutato")]
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="riparazioni", verbose_name="cliente")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="prodotto")
    seriale = models.CharField("numero di serie", max_length=60, blank=True)
    descrizione_bene = models.CharField("bene", max_length=200, blank=True, help_text="se non è un nostro prodotto")
    difetto = models.TextField("difetto segnalato")
    accessori = models.CharField("consegnato con", max_length=200, blank=True, help_text="es. alimentatore, custodia")
    ricevuta_il = models.DateField("ricevuta il", default=timezone.localdate)
    magazzino = models.ForeignKey("magazzino.Magazzino", on_delete=models.PROTECT, related_name="+", verbose_name="ricambi da")
    tecnico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="tecnico")
    stato = models.CharField("stato", max_length=12, choices=STATI, default=RICEVUTA, editable=False)
    in_garanzia = models.BooleanField("in garanzia", default=False, help_text="proposta dalla data di consegna, si può cambiare")
    garanzia_fino_al = models.DateField("garanzia fino al", null=True, blank=True, editable=False)
    recupero_fornitore = models.BooleanField("da recuperare dal fornitore", default=False, editable=False)
    ore = models.DecimalField("ore di lavoro", max_digits=6, decimal_places=2, default=0)
    tariffa = models.DecimalField("tariffa oraria (€)", max_digits=8, decimal_places=2, default=Decimal(40))
    diagnosi = models.TextField("diagnosi e lavoro fatto", blank=True)
    riconsegnata_il = models.DateField("riconsegnata il", null=True, blank=True, editable=False)
    fattura_id = models.PositiveBigIntegerField("fattura", null=True, blank=True, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "riparazione"
        verbose_name_plural = "riparazioni"
        ordering = ["-ricevuta_il", "-pk"]

    def __str__(self):
        return f"{self.numero or 'Riparazione'} · {self.prodotto or self.descrizione_bene} di {self.cliente}"

    @property
    def ricambi(self):
        return sum((r.importo for r in self.righe.all()), Decimal(0))

    @property
    def manodopera(self):
        return (self.ore * self.tariffa).quantize(Decimal("0.01"))

    @property
    def totale(self):
        return Decimal(0) if self.in_garanzia else self.ricambi + self.manodopera


class RigaRicambio(models.Model):
    riparazione = models.ForeignKey(Riparazione, on_delete=models.CASCADE, related_name="righe", verbose_name="riparazione")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, related_name="+", verbose_name="ricambio")
    quantita = models.DecimalField("quantità", max_digits=10, decimal_places=3, default=1)
    prezzo = models.DecimalField("prezzo (€)", max_digits=10, decimal_places=2, null=True, blank=True, help_text="vuoto = prezzo del prodotto")
    scaricato = models.BooleanField("scaricato", default=False, editable=False)

    class Meta:
        verbose_name = "ricambio"
        verbose_name_plural = "ricambi"
        ordering = ["pk"]

    @property
    def importo(self):
        return ((self.prezzo if self.prezzo is not None else self.prodotto.prezzo_vendita) * self.quantita).quantize(Decimal("0.01"))
