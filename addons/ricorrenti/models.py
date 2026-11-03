import calendar
import datetime
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin
from fiscale import calcoli


def piu_mesi(giorno, mesi):
    anno, mese = divmod(giorno.year * 12 + giorno.month - 1 + mesi, 12)
    return datetime.date(anno, mese + 1, min(giorno.day, calendar.monthrange(anno, mese + 1)[1]))


class Canone(AziendaMixin):
    """Un contratto che si fattura a periodi uguali, contati sempre dalla data di inizio."""
    BOZZA, ATTIVO, SOSPESO, DISDETTO, CONCLUSO = "bozza", "attivo", "sospeso", "disdetto", "concluso"
    STATI = [(BOZZA, "Da attivare"), (ATTIVO, "Attivo"), (SOSPESO, "Sospeso"), (DISDETTO, "Disdetto, in corso fino al termine"),
             (CONCLUSO, "Concluso")]
    PERIODICITA = [(1, "Mensile"), (2, "Bimestrale"), (3, "Trimestrale"), (6, "Semestrale"), (12, "Annuale")]
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    nome = models.CharField("nome", max_length=120, help_text="es. Manutenzione del sito, Hosting, Licenza")
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="canoni", verbose_name="cliente")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="canoni", verbose_name="responsabile", help_text="riceve l'avviso prima della scadenza")
    stato = models.CharField("stato", max_length=10, choices=STATI, default=BOZZA, editable=False)
    inizio = models.DateField("inizio", default=timezone.localdate)
    periodicita = models.PositiveSmallIntegerField("si fattura ogni", choices=PERIODICITA, default=1)
    anticipata = models.BooleanField("fattura anticipata", default=True, help_text="all'inizio di ogni periodo; se tolto, alla fine")
    durata_mesi = models.PositiveSmallIntegerField("durata (mesi)", default=12, help_text="0 = senza scadenza")
    rinnovo_tacito = models.BooleanField("rinnovo tacito", default=True, help_text="alla scadenza riparte per la stessa durata")
    preavviso_giorni = models.PositiveSmallIntegerField("preavviso di disdetta (giorni)", default=60)
    adeguamento_istat = models.BooleanField("adeguamento ISTAT", default=False, help_text="compare nella pagina dell'adeguamento annuale")
    termine_pagamento = models.ForeignKey("fiscale.TerminePagamento", on_delete=models.SET_NULL, null=True, blank=True,
                                          verbose_name="pagamento")
    emissione_automatica = models.BooleanField("emetti le fatture da solo", default=False,
                                               help_text="se tolto, le fatture restano in bozza da controllare")
    invio_automatico = models.BooleanField("inviale al cliente per email", default=False, help_text="solo con l'emissione automatica")
    note = models.TextField("note interne", blank=True)
    prossimo_periodo = models.DateField("prossimo periodo da fatturare, dal", null=True, blank=True,
                                        help_text="lo gestisce il sistema; riportalo indietro per rifare un periodo annullato")
    scadenza = models.DateField("scadenza", null=True, blank=True, editable=False)
    cessa_il = models.DateField("cessa il", null=True, blank=True, editable=False)
    disdetto_il = models.DateField("disdetto il", null=True, blank=True, editable=False)
    avviso_per = models.DateField("avviso mandato per la scadenza del", null=True, blank=True, editable=False)
    imponibile = models.DecimalField("importo per periodo", max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "contratto ricorrente"
        verbose_name_plural = "contratti ricorrenti"
        ordering = ["cliente__nome", "-inizio"]

    def __str__(self):
        return f"{self.numero} {self.nome}".strip()

    @property
    def fatturabile(self):
        return self.stato in (self.ATTIVO, self.DISDETTO)

    @property
    def mensile(self):
        """Il valore del contratto riportato al mese."""
        return self.imponibile / self.periodicita

    def dopo(self, giorno):
        """L'inizio del periodo successivo a quello che parte da `giorno`, sempre contato dall'inizio: 31/01, 28/02, 31/03."""
        return piu_mesi(self.inizio, self._mesi_da_inizio(giorno) + self.periodicita)

    def _mesi_da_inizio(self, giorno):
        return (giorno.year - self.inizio.year) * 12 + giorno.month - self.inizio.month

    def allineato(self, giorno):
        mesi = self._mesi_da_inizio(giorno)
        return mesi >= 0 and mesi % self.periodicita == 0 and piu_mesi(self.inizio, mesi) == giorno

    def fine_periodo(self, dal):
        return self.dopo(dal) - datetime.timedelta(days=1)

    def data_fattura(self, dal):
        return dal if self.anticipata else self.fine_periodo(dal)

    def periodo_che_contiene(self, giorno):
        if giorno <= self.inizio:
            return self.inizio
        dal = piu_mesi(self.inizio, self._mesi_da_inizio(giorno) // self.periodicita * self.periodicita)
        return dal if dal <= giorno else piu_mesi(self.inizio, self._mesi_da_inizio(dal) - self.periodicita)

    def fine_termine(self, dal_inizio=None):
        return piu_mesi(dal_inizio or self.inizio, self.durata_mesi) - datetime.timedelta(days=1)

    def limite_disdetta(self):
        return self.scadenza - datetime.timedelta(days=self.preavviso_giorni) if self.scadenza else None

    def ricalcola(self):
        self.imponibile = sum((r.importo for r in self.righe.all()), Decimal(0))
        self.save(update_fields=["imponibile"])

    def clean(self):
        if self.durata_mesi and self.periodicita and self.durata_mesi % self.periodicita:
            raise ValidationError({"durata_mesi": "La durata deve essere un multiplo del periodo di fatturazione, "
                                                  "così l'ultimo periodo non resta a metà."})
        if self.invio_automatico and not self.emissione_automatica:
            raise ValidationError({"invio_automatico": "Si invia da solo solo ciò che si emette da solo."})
        if self.pk:
            prima = type(self).objects.filter(pk=self.pk).values("stato", "inizio", "periodicita").first()
            if prima and prima["stato"] != self.BOZZA and not self.prossimo_periodo:
                raise ValidationError({"prossimo_periodo": "Un contratto attivato deve indicare il prossimo periodo."})
            if prima and prima["stato"] != self.BOZZA and (prima["inizio"] != self.inizio or prima["periodicita"] != self.periodicita):
                raise ValidationError("Inizio e periodicità non cambiano più dopo l'attivazione: "
                                      "conta i periodi già fatturati. Chiudi il contratto e creane uno nuovo.")
        if self.prossimo_periodo and self.inizio and self.periodicita and not self.allineato(self.prossimo_periodo):
            raise ValidationError({"prossimo_periodo": "Questa data non è l'inizio di un periodo del contratto."})


class RigaCanone(models.Model):
    canone = models.ForeignKey(Canone, on_delete=models.CASCADE, related_name="righe", verbose_name="contratto")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True, verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=200, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    prezzo = models.DecimalField("prezzo per periodo (€)", max_digits=12, decimal_places=4, null=True, blank=True,
                                 help_text="vuoto = dal prodotto")
    sconto = models.DecimalField("sconto %", max_digits=5, decimal_places=2, default=0)
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, null=True, blank=True, verbose_name="IVA")
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
        from fiscale.models import AliquotaIva
        if self.prodotto_id:
            self.descrizione = self.descrizione or (self.prodotto.descrizione_vendita or self.prodotto.nome)[:200]
            if self.prezzo is None:
                self.prezzo = self.prodotto.prezzo_vendita
            if self.aliquota_id is None:
                self.aliquota = self.prodotto.aliquota_iva
        if self.aliquota_id is None:
            self.aliquota = AliquotaIva.objects.filter(codice="22").first()
        self.prezzo = self.prezzo if self.prezzo is not None else Decimal(0)
        self.importo = calcoli.importo_riga(self.quantita, self.prezzo, self.sconto)
        super().save(*args, **kwargs)


class FatturaCanone(models.Model):
    """Il periodo già fatturato: uno per contratto, così due giri insieme non fatturano due volte."""
    canone = models.ForeignKey(Canone, on_delete=models.PROTECT, related_name="fatturati", verbose_name="contratto")
    fattura = models.OneToOneField("fatturazione.Fattura", on_delete=models.CASCADE, related_name="da_canone", verbose_name="fattura")
    dal = models.DateField("dal")
    al = models.DateField("al")

    class Meta:
        verbose_name = "periodo fatturato"
        verbose_name_plural = "periodi fatturati"
        ordering = ["-dal"]
        constraints = [models.UniqueConstraint(fields=["canone", "dal"], name="ricorrenti_periodo_unico")]

    def __str__(self):
        return f"{self.canone}: {self.dal:%d/%m/%Y} – {self.al:%d/%m/%Y}"


class Adeguamento(models.Model):
    canone = models.ForeignKey(Canone, on_delete=models.CASCADE, related_name="adeguamenti", verbose_name="contratto")
    data = models.DateField("data", default=timezone.localdate)
    percentuale = models.DecimalField("percentuale", max_digits=5, decimal_places=2)
    prima = models.DecimalField("importo prima", max_digits=14, decimal_places=2)
    dopo = models.DecimalField("importo dopo", max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "adeguamento"
        verbose_name_plural = "adeguamenti"
        ordering = ["-data"]
        constraints = [models.UniqueConstraint(fields=["canone", "data"], name="ricorrenti_adeguamento_unico")]

    def __str__(self):
        return f"{self.canone}: {self.percentuale}% il {self.data:%d/%m/%Y}"
