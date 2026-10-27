from django.conf import settings
from django.db import models

from core.mixins import AziendaMixin, ProprietaMixin


class Tag(models.Model):
    nome = models.CharField("nome", max_length=40, unique=True)
    colore = models.CharField("colore", max_length=7, default="#1e3a8a")

    class Meta:
        verbose_name = "tag"
        verbose_name_plural = "tag"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Attivita(AziendaMixin, ProprietaMixin):
    APERTA, IN_CORSO, FATTA, ANNULLATA = "aperta", "in_corso", "fatta", "annullata"
    STATI = [(APERTA, "Aperta"), (IN_CORSO, "In corso"), (FATTA, "Fatta"), (ANNULLATA, "Annullata")]
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    titolo = models.CharField("titolo", max_length=200)
    descrizione = models.TextField("descrizione", blank=True)
    scadenza = models.DateField("scadenza", null=True, blank=True)
    assegnatario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="attivita_assegnate", verbose_name="assegnatario")
    stato = models.CharField("stato", max_length=12, choices=STATI, default=APERTA)
    tag = models.ManyToManyField(Tag, blank=True, verbose_name="tag")
    creato = models.DateTimeField("creato il", auto_now_add=True)
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "attività"
        verbose_name_plural = "attività"
        ordering = ["-scadenza", "-creato"]

    def __str__(self):
        return self.titolo
