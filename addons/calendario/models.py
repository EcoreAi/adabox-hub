import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.mixins import AziendaMixin


class Evento(AziendaMixin):
    PROMEMORIA = [(0, "Nessuno"), (15, "15 minuti prima"), (60, "1 ora prima"), (1440, "1 giorno prima")]
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    titolo = models.CharField("titolo", max_length=200)
    inizio = models.DateTimeField("inizio")
    fine = models.DateTimeField("fine")
    tutto_il_giorno = models.BooleanField("tutto il giorno", default=False)
    luogo = models.CharField("luogo", max_length=200, blank=True)
    descrizione = models.TextField("descrizione", blank=True)
    organizzatore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="eventi_organizzati", verbose_name="organizzatore")
    partecipanti = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="eventi",
                                          verbose_name="partecipanti")
    contatti = models.ManyToManyField("contatti.Contatto", blank=True, related_name="eventi", verbose_name="contatti")
    privato = models.BooleanField("privato", default=False, help_text="visibile solo a organizzatore e partecipanti")
    promemoria = models.PositiveIntegerField("promemoria", choices=PROMEMORIA, default=15)
    promemoria_inviato = models.BooleanField(default=False, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "evento"
        verbose_name_plural = "eventi"
        ordering = ["inizio"]

    def __str__(self):
        return self.titolo

    def clean(self):
        if self.inizio and self.fine and self.fine < self.inizio:
            raise ValidationError({"fine": "La fine non può precedere l'inizio."})
