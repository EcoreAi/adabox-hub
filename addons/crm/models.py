from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin


class FaseCrm(models.Model):
    nome = models.CharField("nome", max_length=60)
    ordine = models.PositiveSmallIntegerField("ordine", default=10)
    probabilita = models.PositiveSmallIntegerField("probabilità (%)", default=10, validators=[MaxValueValidator(100)])
    vinta = models.BooleanField("fase di vittoria", default=False)

    class Meta:
        verbose_name = "fase"
        verbose_name_plural = "fasi"
        ordering = ["ordine", "pk"]

    def __str__(self):
        return self.nome


class EtichettaCrm(models.Model):
    nome = models.CharField("nome", max_length=60, unique=True)

    class Meta:
        verbose_name = "etichetta"
        verbose_name_plural = "etichette"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class MotivoPerdita(models.Model):
    nome = models.CharField("nome", max_length=100, unique=True)

    class Meta:
        verbose_name = "motivo di perdita"
        verbose_name_plural = "motivi di perdita"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


def fase_iniziale():
    return FaseCrm.objects.order_by("ordine", "pk").values_list("pk", flat=True).first()


class Opportunita(AziendaMixin, ProprietaMixin):
    APERTA, VINTA, PERSA = "aperta", "vinta", "persa"
    STATI = [(APERTA, "Aperta"), (VINTA, "Vinta"), (PERSA, "Persa")]
    PRIORITA = [(0, "Normale"), (1, "Buona"), (2, "Alta"), (3, "Altissima")]
    titolo = models.CharField("titolo", max_length=200)
    contatto = models.ForeignKey("contatti.Contatto", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="opportunita", verbose_name="contatto")
    nome_contatto = models.CharField("nome del contatto", max_length=200, blank=True,
                                     help_text="per i lead non ancora in anagrafica")
    email = models.EmailField("email", blank=True)
    telefono = models.CharField("telefono", max_length=40, blank=True)
    fase = models.ForeignKey(FaseCrm, on_delete=models.PROTECT, default=fase_iniziale, verbose_name="fase")
    stato = models.CharField("stato", max_length=6, choices=STATI, default=APERTA)
    valore_atteso = models.DecimalField("valore atteso (€)", max_digits=12, decimal_places=2, default=0)
    probabilita = models.PositiveSmallIntegerField("probabilità (%)", default=10, validators=[MaxValueValidator(100)])
    chiusura_prevista = models.DateField("chiusura prevista", null=True, blank=True)
    chiusa_il = models.DateField("chiusa il", null=True, blank=True, editable=False)
    commerciale = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="opportunita", verbose_name="commerciale")
    priorita = models.PositiveSmallIntegerField("priorità", choices=PRIORITA, default=0)
    etichette = models.ManyToManyField(EtichettaCrm, blank=True, verbose_name="etichette")
    motivo_perdita = models.ForeignKey(MotivoPerdita, on_delete=models.SET_NULL, null=True, blank=True,
                                       verbose_name="motivo di perdita")
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "opportunità"
        verbose_name_plural = "opportunità"
        ordering = ["-priorita", "chiusura_prevista", "pk"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fase_caricata = self.fase_id

    def __str__(self):
        return self.titolo

    def applica_fase(self):
        """Fase di vittoria → vinta al 100%; uscendo dalla vittoria si riapre; altrimenti la probabilità
        della fase, se il parametro lo prevede e la fase è cambiata."""
        cambiata = self.fase_id != self._fase_caricata
        if self.fase_id and self.fase.vinta:
            self.stato, self.probabilita = self.VINTA, 100
            self.chiusa_il = self.chiusa_il or timezone.localdate()
        elif self.stato == self.VINTA:
            self.stato, self.chiusa_il = self.APERTA, None
        if cambiata and self.stato == self.APERTA and self.fase_id and _probabilita_dalla_fase(self.azienda_id):
            self.probabilita = self.fase.probabilita

    def save(self, *args, **kwargs):
        self.applica_fase()
        if kwargs.get("update_fields") is not None and "fase" in kwargs["update_fields"]:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"stato", "probabilita", "chiusa_il"}
        super().save(*args, **kwargs)
        self._fase_caricata = self.fase_id


def _probabilita_dalla_fase(azienda_id):
    from core import parametri
    from core.models import Azienda
    try:
        return parametri.leggi("crm.probabilita_dalla_fase", Azienda.objects.filter(pk=azienda_id).first())
    except KeyError:                                   # modulo non ancora attivo (es. durante l'installazione)
        return True
