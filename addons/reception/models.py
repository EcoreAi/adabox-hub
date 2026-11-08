"""Le visite: chi entra, da quale azienda, chi lo riceve, quando entra ed esce."""
from django.conf import settings
from django.db import models

from core.mixins import AziendaMixin


class Visita(AziendaMixin):
    nome = models.CharField("nome e cognome", max_length=120)
    societa = models.CharField("azienda del visitatore", max_length=120, blank=True)
    email = models.EmailField("email", blank=True)
    telefono = models.CharField("telefono", max_length=40, blank=True)
    ospite = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="visite_ricevute", verbose_name="chi lo riceve")
    motivo = models.CharField("motivo", max_length=200, blank=True)
    prevista_il = models.DateTimeField("prevista il", null=True, blank=True, help_text="per registrare in anticipo una visita attesa")
    entrata = models.DateTimeField("entrato alle", null=True, blank=True)
    uscita = models.DateTimeField("uscito alle", null=True, blank=True)
    badge = models.CharField("badge", max_length=30, blank=True)
    privacy = models.BooleanField("informativa accettata", default=False)
    creato = models.DateTimeField("registrata il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "visita"
        verbose_name_plural = "visite"
        ordering = ["-entrata", "-prevista_il", "-pk"]

    def __str__(self):
        return f"{self.nome} ({self.societa})" if self.societa else self.nome

    @property
    def stato(self):
        if self.uscita:
            return "uscito"
        return "presente" if self.entrata else "attesa"

    @property
    def nome_breve(self):
        """Per la lista pubblica del tablet: nome e iniziale del cognome, niente azienda."""
        parti = self.nome.split()
        return f"{parti[0]} {parti[-1][:1]}." if len(parti) > 1 else self.nome
