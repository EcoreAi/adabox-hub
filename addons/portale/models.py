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


class ProviderAccesso(models.Model):
    """Un servizio con cui i clienti del portale entrano senza password (OpenID Connect): Google o Microsoft.
    Entra solo chi ha già un accesso al portale con quella email: nessuna registrazione aperta."""
    GOOGLE, MICROSOFT = "google", "microsoft"
    TIPI = [(GOOGLE, "Google"), (MICROSOFT, "Microsoft")]
    tipo = models.CharField("servizio", max_length=12, choices=TIPI, unique=True)
    client_id = models.CharField("client ID", max_length=200)
    segreto_cifrato = models.TextField(blank=True, editable=False)
    tenant = models.CharField("tenant Microsoft", max_length=80, blank=True, default="common",
                              help_text="«common» per tutti gli account, «organizations» solo aziendali, o l'ID di un tenant")
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "accesso con Google o Microsoft"
        verbose_name_plural = "accessi con Google o Microsoft"

    def __str__(self):
        return self.get_tipo_display()

    @property
    def segreto(self):
        from core import cifratura
        return cifratura.decifra(self.segreto_cifrato)


class IdentitaEsterna(models.Model):
    """Un account Google o Microsoft collegato a un utente del portale: dal secondo accesso lo si riconosce da qui."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="identita_esterne",
                               verbose_name="utente")
    tipo = models.CharField("servizio", max_length=12, choices=ProviderAccesso.TIPI)
    soggetto = models.CharField("identificativo nel servizio", max_length=255)
    email = models.EmailField("email", blank=True)
    collegata_il = models.DateTimeField("collegata il", auto_now_add=True)
    ultimo_accesso = models.DateTimeField("ultimo accesso", null=True, blank=True)

    class Meta:
        verbose_name = "account collegato"
        verbose_name_plural = "account collegati"
        constraints = [models.UniqueConstraint(fields=["tipo", "soggetto"], name="portale_identita_unica")]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.email or self.soggetto}"
