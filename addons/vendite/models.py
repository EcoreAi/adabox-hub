from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin
from fiscale import calcoli


class OrdineVendita(AziendaMixin, ProprietaMixin):
    BOZZA, INVIATO, CONFERMATO, ANNULLATO = "bozza", "inviato", "confermato", "annullato"
    STATI = [(BOZZA, "Preventivo"), (INVIATO, "Preventivo inviato"), (CONFERMATO, "Ordine confermato"),
             (ANNULLATO, "Annullato")]
    numero = models.CharField("numero preventivo", max_length=30, blank=True, editable=False, db_index=True)
    numero_ordine = models.CharField("numero ordine", max_length=30, blank=True, editable=False, db_index=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=BOZZA, editable=False)
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="ordini_vendita",
                                verbose_name="cliente")
    data = models.DateField("data", default=timezone.localdate)
    validita = models.DateField("valido fino al", null=True, blank=True)
    listino = models.ForeignKey("prodotti.Listino", on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name="listino")
    termine_pagamento = models.ForeignKey("fiscale.TerminePagamento", on_delete=models.SET_NULL, null=True, blank=True,
                                          verbose_name="pagamento")
    commerciale = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="ordini_vendita", verbose_name="commerciale")
    riferimento_cliente = models.CharField("riferimento del cliente", max_length=100, blank=True)
    note = models.TextField("note per il cliente", blank=True)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2, default=0, editable=False)
    imposta = models.DecimalField("IVA", max_digits=14, decimal_places=2, default=0, editable=False)
    totale = models.DecimalField("totale", max_digits=14, decimal_places=2, default=0, editable=False)
    confermato_il = models.DateField("confermato il", null=True, blank=True, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "preventivo / ordine"
        verbose_name_plural = "preventivi e ordini"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return self.numero_ordine or self.numero or f"Bozza {self.pk}"

    @property
    def modificabile(self):
        return self.stato in (self.BOZZA, self.INVIATO)

    @property
    def titolo_documento(self):
        return "Ordine" if self.stato == self.CONFERMATO else "Preventivo"

    def riepilogo_iva(self):
        return calcoli.riepilogo_iva([(r.importo, r.aliquota) for r in self.righe.select_related("aliquota")])

    def ricalcola(self):
        self.imponibile, self.imposta, self.totale = calcoli.totali(
            [(r.importo, r.aliquota) for r in self.righe.select_related("aliquota")])
        self.save(update_fields=["imponibile", "imposta", "totale"])

    def clean(self):
        if self.validita and self.data and self.validita < self.data:
            raise ValidationError({"validita": "La validità non può precedere la data del preventivo."})


class RigaVendita(models.Model):
    ordine = models.ForeignKey(OrdineVendita, on_delete=models.CASCADE, related_name="righe", verbose_name="ordine")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4, null=True, blank=True,
                                 help_text="vuoto = dal listino o dal prodotto")
    sconto = models.DecimalField("sconto %", max_digits=5, decimal_places=2, default=0)
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="IVA")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]

    def __str__(self):
        return self.descrizione

    def clean(self):
        if not self.prodotto_id and not self.descrizione:
            raise ValidationError("Indica un prodotto o una descrizione.")
        if self.quantita is not None and self.quantita <= 0:
            raise ValidationError({"quantita": "La quantità deve essere positiva."})
        if self.sconto is not None and not 0 <= self.sconto <= 100:
            raise ValidationError({"sconto": "Lo sconto va da 0 a 100."})

    def save(self, *args, **kwargs):
        """Valori mancanti dal prodotto e dal listino del documento; importo ricalcolato."""
        from fiscale.models import AliquotaIva
        from prodotti.prezzi import prezzo
        if self.prodotto_id:
            if not self.descrizione:
                self.descrizione = (self.prodotto.descrizione_vendita or self.prodotto.nome)[:250]
            if self.prezzo is None:
                self.prezzo = prezzo(self.prodotto, self.ordine.listino, self.quantita)
            if self.aliquota_id is None:
                self.aliquota = self.prodotto.aliquota_iva
        if self.aliquota_id is None:
            self.aliquota = AliquotaIva.objects.filter(codice="22").first()
        self.prezzo = self.prezzo if self.prezzo is not None else Decimal(0)
        self.importo = calcoli.importo_riga(self.quantita, self.prezzo, self.sconto)
        super().save(*args, **kwargs)
