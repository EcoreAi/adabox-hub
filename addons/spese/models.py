import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin
from core.storage import StoragePrivato


class CategoriaSpesa(models.Model):
    nome = models.CharField("nome", max_length=80, unique=True)
    limite = models.DecimalField("limite per spesa (€)", max_digits=10, decimal_places=2, null=True, blank=True,
                                 help_text="vuoto: nessun limite")
    ricevuta_obbligatoria = models.BooleanField("ricevuta obbligatoria", default=True)
    chilometrica = models.BooleanField("rimborso chilometrico", default=False,
                                       help_text="si indicano i km e l'importo è km × tariffa")
    tariffa_km = models.DecimalField("tariffa al km (€)", max_digits=8, decimal_places=4, default=Decimal(0))
    attiva = models.BooleanField("attiva", default=True)

    class Meta:
        verbose_name = "categoria di spesa"
        verbose_name_plural = "categorie di spesa"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class NotaSpese(AziendaMixin):
    BOZZA, INVIATA, APPROVATA, RIFIUTATA, RIMBORSATA = "bozza", "inviata", "approvata", "rifiutata", "rimborsata"
    STATI = [(BOZZA, "Bozza"), (INVIATA, "Da approvare"), (APPROVATA, "Approvata, da rimborsare"),
             (RIFIUTATA, "Rifiutata"), (RIMBORSATA, "Rimborsata")]
    numero = models.CharField("numero", max_length=30, blank=True, editable=False)
    dipendente = models.ForeignKey("personale.Dipendente", on_delete=models.PROTECT, related_name="note_spese",
                                   verbose_name="dipendente")
    titolo = models.CharField("titolo", max_length=150, help_text="es. Trasferta Milano, fiera di ottobre")
    stato = models.CharField("stato", max_length=10, choices=STATI, default=BOZZA, editable=False)
    totale = models.DecimalField("totale", max_digits=12, decimal_places=2, default=0, editable=False)
    inviata_il = models.DateTimeField("inviata il", null=True, blank=True, editable=False)
    decisa_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="decisa da", editable=False)
    nota_decisione = models.CharField("nota", max_length=250, blank=True, editable=False)
    rimborsata_il = models.DateField("rimborsata il", null=True, blank=True, editable=False)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "nota spese"
        verbose_name_plural = "note spese"
        ordering = ["-pk"]
        permissions = [("vedi_tutte_note", "Vede, approva e rimborsa le note spese di tutti")]

    def __str__(self):
        return f"{self.numero or 'Nota spese'} · {self.titolo}"

    @property
    def modificabile(self):
        return self.stato == self.BOZZA

    def ricalcola(self):
        self.totale = sum((r.importo for r in self.righe.all()), Decimal(0))
        self.save(update_fields=["totale"])


def _percorso(instance, filename):
    return f"spese/{timezone.now():%Y/%m}/{uuid.uuid4().hex}-{filename}"


class RigaSpesa(models.Model):
    nota = models.ForeignKey(NotaSpese, on_delete=models.CASCADE, related_name="righe", verbose_name="nota")
    data = models.DateField("data", default=timezone.localdate)
    categoria = models.ForeignKey(CategoriaSpesa, on_delete=models.PROTECT, verbose_name="categoria")
    descrizione = models.CharField("descrizione", max_length=200)
    km = models.DecimalField("km", max_digits=8, decimal_places=1, null=True, blank=True)
    importo = models.DecimalField("importo (€)", max_digits=10, decimal_places=2, null=True, blank=True)
    ricevuta = models.FileField("ricevuta", upload_to=_percorso, storage=StoragePrivato(), max_length=300, blank=True)

    class Meta:
        verbose_name = "spesa"
        verbose_name_plural = "spese"
        ordering = ["data", "pk"]

    def __str__(self):
        return f"{self.data:%d/%m/%Y} · {self.descrizione}"

    def clean(self):
        errori = {}
        if self.categoria_id and self.categoria.chilometrica:
            if not self.km or self.km <= 0:
                errori["km"] = "Indica i chilometri."
        elif self.importo is None or self.importo <= 0:
            errori["importo"] = "Indica l'importo."
        elif self.categoria_id and self.categoria.limite and self.importo > self.categoria.limite:
            errori["importo"] = f"Oltre il limite di {self.categoria.limite} € per {self.categoria}."
        if self.data and self.data > timezone.localdate():
            errori["data"] = "La data è nel futuro."
        if errori:
            raise ValidationError(errori)

    def save(self, *args, **kwargs):
        if self.categoria.chilometrica and self.km:
            self.importo = (self.km * self.categoria.tariffa_km).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)
