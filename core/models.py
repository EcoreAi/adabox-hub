from django.db import models


class Cliente(models.Model):
    """Modello di esempio: serve solo a mostrare admin e tabelle con dati veri."""
    nome = models.CharField("nome", max_length=120)
    email = models.EmailField("email", blank=True)
    attivo = models.BooleanField("attivo", default=True)
    note = models.TextField("note", blank=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clienti"
        ordering = ["-creato"]

    def __str__(self):
        return self.nome
