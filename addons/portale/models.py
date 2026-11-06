from django.conf import settings
from django.db import models


class AccessoPortale(models.Model):
    """L'accesso di un cliente al portale: un utente esterno legato a un contatto (persona di un'azienda cliente).
    Vede i documenti e le richieste della sua azienda, ognuno dalla sezione dell'app che lo gestisce."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accesso_portale",
                                  verbose_name="utente")
    contatto = models.ForeignKey("contatti.Contatto", on_delete=models.CASCADE, related_name="accessi_portale",
                                 verbose_name="contatto")
    invitato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="invitato da")
    invitato_il = models.DateTimeField("invitato il", auto_now_add=True)

    class Meta:
        verbose_name = "accesso al portale"
        verbose_name_plural = "accessi al portale"

    def __str__(self):
        return f"{self.utente} · {self.contatto}"

    @property
    def cliente(self):
        """L'azienda cliente (il contatto stesso se è un'azienda)."""
        return self.contatto.societa or self.contatto

    @property
    def azienda(self):
        """L'azienda (dell'istanza) a cui appartiene il cliente: i documenti del portale si filtrano anche su questa."""
        return self.contatto.azienda

    def contatti(self):
        """Il cliente e tutte le sue persone: i loro documenti e richieste sono visibili dal portale."""
        cliente = self.cliente
        return [cliente.pk, *cliente.persone.values_list("pk", flat=True)]
