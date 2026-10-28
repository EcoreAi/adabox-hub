from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin
from fiscale import calcoli


class DatiFiscali(models.Model):
    """Dati dell'azienda che emette le fatture (estensione uno-a-uno di core.Azienda)."""
    REGIMI = [("RF01", "RF01 · Ordinario"), ("RF02", "RF02 · Contribuenti minimi"), ("RF04", "RF04 · Agricoltura"),
              ("RF19", "RF19 · Forfettario")]
    azienda = models.OneToOneField("core.Azienda", on_delete=models.CASCADE, related_name="dati_fiscali",
                                   verbose_name="azienda")
    regime_fiscale = models.CharField("regime fiscale", max_length=4, choices=REGIMI, default="RF01")
    iban = models.CharField("IBAN", max_length=34, blank=True)
    banca = models.CharField("banca", max_length=80, blank=True)
    rea_ufficio = models.CharField("REA: provincia dell'ufficio", max_length=2, blank=True)
    rea_numero = models.CharField("REA: numero", max_length=20, blank=True)
    capitale_sociale = models.DecimalField("capitale sociale", max_digits=14, decimal_places=2, null=True, blank=True)
    socio_unico = models.CharField("soci", max_length=2, blank=True,
                                   choices=[("", "—"), ("SU", "Socio unico"), ("SM", "Più soci")])
    progressivo_invio = models.PositiveIntegerField("ultimo progressivo di invio", default=0, editable=False)

    class Meta:
        verbose_name = "dati fiscali"
        verbose_name_plural = "dati fiscali"

    def __str__(self):
        return f"Dati fiscali di {self.azienda}"


class Fattura(AziendaMixin, ProprietaMixin):
    FATTURA, NOTA_CREDITO = "TD01", "TD04"
    TIPI = [(FATTURA, "Fattura"), (NOTA_CREDITO, "Nota di credito")]
    BOZZA, EMESSA, ANNULLATA = "bozza", "emessa", "annullata"
    STATI = [(BOZZA, "Bozza"), (EMESSA, "Emessa"), (ANNULLATA, "Annullata")]
    tipo = models.CharField("tipo", max_length=4, choices=TIPI, default=FATTURA)
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=BOZZA, editable=False)
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="fatture",
                                verbose_name="cliente")
    data = models.DateField("data", default=timezone.localdate)
    termine_pagamento = models.ForeignKey("fiscale.TerminePagamento", on_delete=models.SET_NULL, null=True, blank=True,
                                          verbose_name="pagamento")
    ordine = models.ForeignKey("vendite.OrdineVendita", on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="fatture", verbose_name="ordine di vendita", editable=False)
    fattura_origine = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True,
                                        related_name="note_credito", verbose_name="fattura stornata", editable=False)
    causale = models.CharField("causale", max_length=200, blank=True)
    note = models.TextField("note", blank=True)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2, default=0, editable=False)
    imposta = models.DecimalField("IVA", max_digits=14, decimal_places=2, default=0, editable=False)
    totale = models.DecimalField("totale", max_digits=14, decimal_places=2, default=0, editable=False)
    pagata = models.BooleanField("incassata", default=False, editable=False)
    emessa_il = models.DateTimeField("emessa il", null=True, blank=True, editable=False)
    progressivo_invio = models.CharField("progressivo di invio", max_length=5, blank=True, editable=False,
                                         help_text="assegnato alla prima generazione dell'XML")

    class Meta(AziendaMixin.Meta):
        verbose_name = "fattura"
        verbose_name_plural = "fatture"
        ordering = ["-data", "-pk"]

    def __str__(self):
        prefisso = "Nota di credito" if self.tipo == self.NOTA_CREDITO else "Fattura"
        return f"{prefisso} {self.numero}" if self.numero else f"{prefisso} in bozza {self.pk}"

    @property
    def modificabile(self):
        return self.stato == self.BOZZA

    @property
    def segno(self):
        return Decimal(-1) if self.tipo == self.NOTA_CREDITO else Decimal(1)

    def riepilogo_iva(self):
        return calcoli.riepilogo_iva([(r.importo, r.aliquota) for r in self.righe.select_related("aliquota")])

    def ricalcola(self):
        self.imponibile, self.imposta, self.totale = calcoli.totali(
            [(r.importo, r.aliquota) for r in self.righe.select_related("aliquota")])
        self.save(update_fields=["imponibile", "imposta", "totale"])


class RigaFattura(models.Model):
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="righe", verbose_name="fattura")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4, null=True, blank=True)
    sconto = models.DecimalField("sconto %", max_digits=5, decimal_places=2, default=0)
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="IVA")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.prodotto_id and not self.descrizione:
            raise ValidationError("Indica un prodotto o una descrizione.")
        if self.quantita is not None and self.quantita <= 0:
            raise ValidationError({"quantita": "La quantità deve essere positiva."})

    def save(self, *args, **kwargs):
        from fiscale.models import AliquotaIva
        if self.prodotto_id:
            self.descrizione = self.descrizione or (self.prodotto.descrizione_vendita or self.prodotto.nome)[:250]
            if self.prezzo is None:
                self.prezzo = self.prodotto.prezzo_vendita
            if self.aliquota_id is None:
                self.aliquota = self.prodotto.aliquota_iva
        if self.aliquota_id is None:
            self.aliquota = AliquotaIva.objects.filter(codice="22").first()
        self.prezzo = self.prezzo if self.prezzo is not None else Decimal(0)
        self.importo = calcoli.importo_riga(self.quantita, self.prezzo, self.sconto)
        super().save(*args, **kwargs)


class Scadenza(models.Model):
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="scadenze", verbose_name="fattura")
    data = models.DateField("scadenza")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2)
    modalita = models.CharField("modalità", max_length=4, default="MP05")
    pagata = models.BooleanField("incassata", default=False)
    pagata_il = models.DateField("incassata il", null=True, blank=True)

    class Meta:
        verbose_name = "scadenza"
        verbose_name_plural = "scadenze"
        ordering = ["data", "pk"]

    def __str__(self):
        return f"{self.fattura} · {self.data:%d/%m/%Y} · {self.importo} €"
