from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from core.mixins import AziendaMixin


class Regola(AziendaMixin):
    """Quando succede `evento`, se valgono le `condizioni`, fai le `azioni`. Nasce spenta: si accende dopo averla vista."""
    nome = models.CharField("nome", max_length=120)
    evento = models.CharField("quando", max_length=50)
    giorni = models.PositiveSmallIntegerField("giorni", default=0)
    condizioni = models.JSONField("condizioni", default=list, blank=True)
    azioni = models.JSONField("azioni", default=list)
    attiva = models.BooleanField("attiva", default=False)
    attivata_il = models.DateTimeField("attivata il", null=True, blank=True)
    creata = models.DateTimeField("creata il", auto_now_add=True)
    creata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                  verbose_name="creata da")

    class Meta(AziendaMixin.Meta):
        verbose_name = "regola"
        verbose_name_plural = "regole"
        ordering = ["-attiva", "nome"]

    def __str__(self):
        return self.nome


class Esecuzione(models.Model):
    """Una volta in cui la regola è scattata su un record. `chiave` impedisce di rifarlo per gli eventi a tempo."""
    FATTA, ERRORE, SALTATA = "fatta", "errore", "saltata"
    ESITI = [(FATTA, "Fatta"), (ERRORE, "Con errori"), (SALTATA, "Saltata")]
    regola = models.ForeignKey(Regola, on_delete=models.CASCADE, related_name="esecuzioni", verbose_name="regola")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    nome_record = models.CharField("record", max_length=200)
    chiave = models.CharField("chiave", max_length=60, null=True, blank=True)
    extra = models.JSONField("valori dell'evento", default=dict, blank=True)
    esito = models.CharField("esito", max_length=8, choices=ESITI, default=FATTA)
    dettaglio = models.JSONField("cosa è successo", default=list, blank=True)
    creata = models.DateTimeField("il", auto_now_add=True)

    class Meta:
        verbose_name = "esecuzione"
        verbose_name_plural = "esecuzioni"
        ordering = ["-creata", "-pk"]
        constraints = [models.UniqueConstraint(fields=["regola", "content_type", "object_id", "chiave"],
                                               name="esecuzione_una_volta")]
        indexes = [models.Index(fields=["regola", "-creata"])]

    def __str__(self):
        return f"{self.regola} · {self.nome_record}"
