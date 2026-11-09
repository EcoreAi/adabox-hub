from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.mixins import AziendaMixin


class Finanziamento(AziendaMixin):
    MUTUO, FINANZIAMENTO, SOCI, ALTRO = "mutuo", "finanziamento", "soci", "altro"
    TIPI = [(MUTUO, "Mutuo"), (FINANZIAMENTO, "Finanziamento bancario"), (SOCI, "Finanziamento soci"), (ALTRO, "Altro")]
    FRANCESE, ITALIANO = "francese", "italiano"
    AMMORTAMENTI = [(FRANCESE, "Francese (rata costante)"), (ITALIANO, "Italiano (quota capitale costante)")]
    PERIODI = [(1, "Mensile"), (3, "Trimestrale"), (6, "Semestrale"), (12, "Annuale")]
    ATTIVO, ESTINTO = "attivo", "estinto"
    STATI = [(ATTIVO, "In corso"), (ESTINTO, "Estinto")]

    nome = models.CharField("nome", max_length=120, help_text="es. Mutuo capannone")
    tipo = models.CharField("tipo", max_length=15, choices=TIPI, default=FINANZIAMENTO)
    ente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, null=True, blank=True, related_name="finanziamenti",
                             verbose_name="ente finanziatore")
    numero_contratto = models.CharField("numero di contratto", max_length=60, blank=True)
    capitale = models.DecimalField("capitale", max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    tasso = models.DecimalField("tasso annuo (%)", max_digits=6, decimal_places=3, default=0,
                                validators=[MinValueValidator(Decimal(0))])
    durata = models.PositiveIntegerField("durata (mesi)", validators=[MinValueValidator(1)])
    periodicita = models.PositiveSmallIntegerField("rate", choices=PERIODI, default=1)
    ammortamento = models.CharField("ammortamento", max_length=10, choices=AMMORTAMENTI, default=FRANCESE)
    erogato_il = models.DateField("erogato il")
    prima_rata = models.DateField("prima rata")
    preammortamento = models.PositiveIntegerField("rate di preammortamento", default=0,
                                                  help_text="rate di soli interessi prima dell'ammortamento")
    spese_rata = models.DecimalField("spese per rata", max_digits=10, decimal_places=2, default=0)
    iban_addebito = models.CharField("conto di addebito (IBAN)", max_length=34, blank=True)
    stato = models.CharField("stato", max_length=8, choices=STATI, default=ATTIVO, editable=False)
    note = models.TextField("note", blank=True)
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="responsabile")

    class Meta(AziendaMixin.Meta):
        verbose_name = "finanziamento"
        verbose_name_plural = "finanziamenti"
        ordering = ["stato", "-erogato_il"]

    def __str__(self):
        return self.nome

    def clean(self):
        if self.durata and self.periodicita and self.durata % self.periodicita:
            raise ValidationError({"durata": "La durata deve essere un multiplo della periodicità delle rate."})
        if self.prima_rata and self.erogato_il and self.prima_rata < self.erogato_il:
            raise ValidationError({"prima_rata": "La prima rata non può precedere l'erogazione."})
        if self.durata and self.periodicita and self.preammortamento >= self.durata // self.periodicita:
            raise ValidationError({"preammortamento": "Il preammortamento deve lasciare almeno una rata di ammortamento."})

    @property
    def numero_rate(self):
        return self.durata // self.periodicita

    def debito_residuo(self, al=None):
        """Capitale ancora da restituire: quello iniziale meno le quote capitale delle rate pagate (fino al giorno `al`)."""
        pagate = self.rate.filter(pagata=True)
        if al:
            pagate = pagate.filter(pagata_il__lte=al)
        return self.capitale - (pagate.aggregate(s=models.Sum("quota_capitale"))["s"] or 0)


class RataFinanziamento(AziendaMixin):
    finanziamento = models.ForeignKey(Finanziamento, on_delete=models.CASCADE, related_name="rate", verbose_name="finanziamento")
    numero = models.PositiveIntegerField("numero")
    data = models.DateField("scadenza")
    quota_capitale = models.DecimalField("quota capitale", max_digits=14, decimal_places=2, default=0)
    quota_interessi = models.DecimalField("quota interessi", max_digits=14, decimal_places=2, default=0)
    spese = models.DecimalField("spese", max_digits=10, decimal_places=2, default=0)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0)
    debito_residuo = models.DecimalField("debito residuo dopo la rata", max_digits=14, decimal_places=2, default=0)
    pagata = models.BooleanField("pagata", default=False)
    pagata_il = models.DateField("pagata il", null=True, blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "rata"
        verbose_name_plural = "rate"
        ordering = ["data", "finanziamento_id", "numero"]
        constraints = [models.UniqueConstraint(fields=["finanziamento", "numero"], name="finanziamenti_rata_unica")]

    def __str__(self):
        return f"{self.finanziamento} · rata {self.numero} del {self.data:%d/%m/%Y}"

    def save(self, *args, **kwargs):
        if self.azienda_id is None and self.finanziamento_id:
            self.azienda_id = self.finanziamento.azienda_id
        super().save(*args, **kwargs)
