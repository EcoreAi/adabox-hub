"""Le caselle di posta e i calendari degli utenti su Google o Microsoft, e ciò che ne è passato in adabox."""
import secrets

from django.conf import settings
from django.db import models

from core import cifratura
from core.mixins import AziendaMixin

GOOGLE, MICROSOFT = "google", "microsoft"
TIPI = [(GOOGLE, "Google"), (MICROSOFT, "Microsoft")]


class ServizioOAuth(models.Model):
    """L'applicazione registrata dall'istanza su Google Cloud o su Microsoft Entra, con cui gli utenti collegano la
    propria casella. Una per servizio."""
    tipo = models.CharField("servizio", max_length=12, choices=TIPI, unique=True)
    client_id = models.CharField("client ID", max_length=200)
    segreto_cifrato = models.TextField(blank=True, editable=False)
    tenant = models.CharField("tenant Microsoft", max_length=80, blank=True, default="common",
                              help_text="«common» per tutti gli account, «organizations» solo aziendali, o l'ID del vostro tenant")
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "servizio di posta"
        verbose_name_plural = "servizi di posta"
        ordering = ["tipo"]

    def __str__(self):
        return self.get_tipo_display()

    def segreto(self):
        return cifratura.decifra(self.segreto_cifrato)


class Casella(AziendaMixin):
    """La casella e il calendario di un utente. L'azienda è quella in cui si cercano i contatti delle email e in cui
    nascono gli eventi."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="caselle_posta", verbose_name="utente")
    tipo = models.CharField("servizio", max_length=12, choices=TIPI)
    email = models.EmailField("indirizzo")
    posta = models.BooleanField("email con i clienti", default=True,
                                help_text="le email scambiate con i contatti finiscono nel loro storico; le altre non si leggono")
    calendario = models.BooleanField("calendario", default=True,
                                     help_text="gli appuntamenti arrivano in adabox e quelli che organizzi qui partono verso il calendario")
    refresh_cifrato = models.TextField(blank=True, editable=False)
    accesso_cifrato = models.TextField(blank=True, editable=False)
    accesso_scade = models.DateTimeField(null=True, blank=True, editable=False)
    cursore_posta = models.DateTimeField("posta letta fino a", null=True, blank=True, editable=False)
    cursore_calendario = models.DateTimeField("calendario letto fino a", null=True, blank=True, editable=False)
    ultimo_giro = models.DateTimeField("ultimo giro", null=True, blank=True, editable=False)
    ultimo_esito = models.CharField("ultimo esito", max_length=500, blank=True, editable=False)
    in_errore = models.BooleanField("da ricollegare", default=False, editable=False)
    collegata_il = models.DateTimeField("collegata il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "casella"
        verbose_name_plural = "caselle"
        ordering = ["utente", "tipo"]
        constraints = [models.UniqueConstraint(fields=["utente", "tipo"], name="posta_una_casella_per_servizio")]

    def __str__(self):
        return f"{self.email} ({self.get_tipo_display()})"

    def refresh_token(self):
        return cifratura.decifra(self.refresh_cifrato)


class EmailSincronizzata(models.Model):
    """Un'email con almeno un contatto, già scritta nello storico dei record: non si riscrive. Le email senza
    contatti non lasciano traccia."""
    casella = models.ForeignKey(Casella, on_delete=models.CASCADE, related_name="email_sincronizzate", verbose_name="casella")
    id_esterno = models.CharField("identificativo nel servizio", max_length=255)
    message_id = models.CharField("Message-ID", max_length=255, db_index=True)
    mittente = models.EmailField("mittente", blank=True)
    oggetto = models.CharField("oggetto", max_length=255, blank=True)
    ricevuta_il = models.DateTimeField("ricevuta il", null=True, blank=True)
    record = models.JSONField("scritta su", default=list, help_text="[[content type, id], ...]")

    class Meta:
        verbose_name = "email sincronizzata"
        verbose_name_plural = "email sincronizzate"
        ordering = ["-ricevuta_il", "-pk"]
        constraints = [models.UniqueConstraint(fields=["casella", "id_esterno"], name="posta_email_unica")]

    def __str__(self):
        return self.oggetto or self.message_id


class EventoCollegato(models.Model):
    """Questo evento di adabox è quell'evento del calendario esterno. L'impronta dei campi passati evita i rimbalzi."""
    casella = models.ForeignKey(Casella, on_delete=models.CASCADE, related_name="eventi", verbose_name="casella")
    evento = models.ForeignKey("calendario.Evento", on_delete=models.CASCADE, related_name="collegamenti_posta", verbose_name="evento")
    id_esterno = models.CharField("identificativo nel calendario", max_length=1024)
    impronta = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "evento collegato"
        verbose_name_plural = "eventi collegati"
        constraints = [models.UniqueConstraint(fields=["casella", "evento"], name="posta_evento_unico")]
        indexes = [models.Index(fields=["casella", "id_esterno"])]

    def __str__(self):
        return f"{self.evento} ↔ {self.id_esterno[:40]}"


def _token():
    return secrets.token_urlsafe(32)


class FeedCalendario(models.Model):
    """L'indirizzo segreto con cui un utente abbona Google, Outlook o il telefono ai propri appuntamenti di adabox."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="feed_calendario", verbose_name="utente")
    token = models.CharField(max_length=64, unique=True, default=_token, editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta:
        verbose_name = "feed del calendario"
        verbose_name_plural = "feed del calendario"

    def __str__(self):
        return f"Feed di {self.utente}"

    def rinnova(self):
        self.token = _token()
        self.save(update_fields=["token"])
