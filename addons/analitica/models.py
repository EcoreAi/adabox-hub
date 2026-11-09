"""Contabilità analitica senza mastro: assi (centro di costo, commessa…), voci di ogni asse, imputazioni delle righe dei
documenti (anche ripartite in percentuale), modelli di ripartizione e budget per voce e periodo."""
from decimal import Decimal

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from core.mixins import AziendaMixin


class Asse(AziendaMixin):
    nome = models.CharField("nome", max_length=60, help_text="es. Centro di costo, Commessa, Linea di prodotto")
    ordine = models.PositiveIntegerField("ordine", default=10)

    class Meta(AziendaMixin.Meta):
        verbose_name = "asse analitico"
        verbose_name_plural = "assi analitici"
        ordering = ["ordine", "nome"]

    def __str__(self):
        return self.nome


class Voce(AziendaMixin):
    asse = models.ForeignKey(Asse, on_delete=models.CASCADE, related_name="voci", verbose_name="asse")
    codice = models.CharField("codice", max_length=20, blank=True)
    nome = models.CharField("nome", max_length=100)
    progetto_id = models.PositiveBigIntegerField("progetto", null=True, blank=True,
                                                 help_text="la commessa del modulo Progetti a cui corrisponde, se c'è")
    attiva = models.BooleanField("attiva", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "voce analitica"
        verbose_name_plural = "voci analitiche"
        ordering = ["asse__ordine", "codice", "nome"]

    def __str__(self):
        return f"{self.codice} {self.nome}".strip()

    @property
    def progetto(self):
        from django.apps import apps
        if not self.progetto_id or not apps.is_installed("progetti"):
            return None
        from progetti.models import Progetto
        return Progetto.objects.filter(pk=self.progetto_id).first()


class Imputazione(AziendaMixin):
    """Una riga di documento (o la sua parte in percentuale) su una voce di un asse."""
    voce = models.ForeignKey(Voce, on_delete=models.PROTECT, related_name="imputazioni", verbose_name="voce")
    tipo_riga = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    id_riga = models.PositiveBigIntegerField()
    riga = GenericForeignKey("tipo_riga", "id_riga")
    percentuale = models.DecimalField("percentuale", max_digits=6, decimal_places=2, default=Decimal(100))

    class Meta(AziendaMixin.Meta):
        verbose_name = "imputazione"
        verbose_name_plural = "imputazioni"
        ordering = ["pk"]
        indexes = [models.Index(fields=["tipo_riga", "id_riga"])]

    def __str__(self):
        return f"{self.voce} · {self.percentuale}%"

    def clean(self):
        if self.percentuale is not None and not 0 < self.percentuale <= 100:
            raise ValidationError({"percentuale": "Fra 0 e 100."})


class ModelloRipartizione(AziendaMixin):
    """Una ripartizione che si ripete (es. affitto: 60% Produzione, 40% Uffici), da applicare in un colpo."""
    nome = models.CharField("nome", max_length=80)

    class Meta(AziendaMixin.Meta):
        verbose_name = "modello di ripartizione"
        verbose_name_plural = "modelli di ripartizione"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def controlla(self):
        righe = list(self.righe.select_related("voce"))
        assi = {r.voce.asse_id for r in righe}
        totale = sum((r.percentuale for r in righe), Decimal(0))
        if not righe:
            raise ValidationError("Il modello non ha righe.")
        if len(assi) > 1:
            raise ValidationError("Le voci di un modello sono dello stesso asse.")
        if totale > 100:
            raise ValidationError(f"Le percentuali fanno {totale}%: al massimo 100.")
        return righe


class RigaModello(models.Model):
    modello = models.ForeignKey(ModelloRipartizione, on_delete=models.CASCADE, related_name="righe", verbose_name="modello")
    voce = models.ForeignKey(Voce, on_delete=models.PROTECT, related_name="+", verbose_name="voce")
    percentuale = models.DecimalField("percentuale", max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = "riga del modello"
        verbose_name_plural = "righe del modello"
        ordering = ["pk"]


class Budget(AziendaMixin):
    """Quanto si prevede di incassare e spendere su una voce in un periodo, per categoria."""
    voce = models.ForeignKey(Voce, on_delete=models.CASCADE, related_name="budget", verbose_name="voce")
    nome = models.CharField("nome", max_length=80, blank=True, help_text="es. Budget 2026")
    dal = models.DateField("dal")
    al = models.DateField("al")
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "budget"
        verbose_name_plural = "budget"
        ordering = ["-dal", "voce__nome"]

    def __str__(self):
        return self.nome or f"Budget {self.voce} {self.dal:%Y}"

    def clean(self):
        if self.dal and self.al and self.al < self.dal:
            raise ValidationError({"al": "La fine viene dopo l'inizio."})


class RigaBudget(models.Model):
    RICAVI, ACQUISTI, SPESE, ORE = "ricavi", "acquisti", "spese", "ore"
    CATEGORIE = [(RICAVI, "Ricavi (fatture emesse)"), (ACQUISTI, "Costi esterni (fatture ricevute)"),
                 (SPESE, "Note spese"), (ORE, "Costo delle ore (dal timesheet)")]
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="righe", verbose_name="budget")
    categoria = models.CharField("categoria", max_length=10, choices=CATEGORIE)
    importo = models.DecimalField("importo (€)", max_digits=14, decimal_places=2)

    class Meta:
        verbose_name = "riga del budget"
        verbose_name_plural = "righe del budget"
        ordering = ["pk"]
