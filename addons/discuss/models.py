from django.conf import settings
from django.db import models


class Canale(models.Model):
    """Conversazione: canale pubblico (chiunque entra), privato (su invito) o diretto (tra persone scelte)."""
    PUBBLICO, PRIVATO, DIRETTO = "pubblico", "privato", "diretto"
    TIPI = [(PUBBLICO, "Pubblico"), (PRIVATO, "Privato"), (DIRETTO, "Diretto")]
    nome = models.CharField("nome", max_length=80, blank=True)
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    tipo = models.CharField("tipo", max_length=10, choices=TIPI, default=PUBBLICO)
    membri = models.ManyToManyField(settings.AUTH_USER_MODEL, through="Iscrizione", related_name="canali_discuss",
                                    verbose_name="membri")
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="creato da", editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    archiviato = models.BooleanField("archiviato", default=False)

    class Meta:
        verbose_name = "canale"
        verbose_name_plural = "canali"
        ordering = ["nome", "pk"]

    def __str__(self):
        return self.nome or f"Conversazione {self.pk}"

    @property
    def diretto(self):
        return self.tipo == self.DIRETTO

    def titolo_per(self, utente):
        """Il nome mostrato: per i messaggi diretti, gli altri partecipanti."""
        if not self.diretto:
            return f"# {self.nome}"
        altri = [u.get_full_name() or u.username for u in self.membri.all() if u.pk != utente.pk]
        return ", ".join(altri) or "Solo tu"


class Iscrizione(models.Model):
    TUTTO, MENZIONI, NIENTE = "tutto", "menzioni", "niente"
    NOTIFICHE = [(TUTTO, "Tutti i messaggi"), (MENZIONI, "Solo le menzioni"), (NIENTE, "Niente")]
    canale = models.ForeignKey(Canale, on_delete=models.CASCADE, related_name="iscrizioni")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="iscrizioni_discuss")
    ultimo_letto = models.PositiveBigIntegerField("ultimo messaggio letto", default=0)
    notifiche = models.CharField("notifiche", max_length=10, choices=NOTIFICHE, default=MENZIONI)
    entrato = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "iscrizione"
        verbose_name_plural = "iscrizioni"
        constraints = [models.UniqueConstraint(fields=["canale", "utente"], name="discuss_iscrizione_unica")]


class Messaggio(models.Model):
    canale = models.ForeignKey(Canale, on_delete=models.CASCADE, related_name="messaggi", verbose_name="canale")
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+",
                               verbose_name="autore")
    corpo = models.TextField("testo", blank=True)
    creato = models.DateTimeField("inviato il", auto_now_add=True)
    modificato_il = models.DateTimeField("modificato il", null=True, blank=True)
    eliminato = models.BooleanField("eliminato", default=False)

    class Meta:
        verbose_name = "messaggio"
        verbose_name_plural = "messaggi"
        ordering = ["pk"]
        indexes = [models.Index(fields=["canale", "id"])]

    def __str__(self):
        return f"{self.autore}: {self.corpo[:40]}"


class Notifica(models.Model):
    """Voce della posta in arrivo: una menzione, un messaggio diretto, un messaggio su un record seguito."""
    MENZIONE, DIRETTO, CANALE, RECORD = "menzione", "diretto", "canale", "record"
    TIPI = [(MENZIONE, "Menzione"), (DIRETTO, "Messaggio diretto"), (CANALE, "Messaggio nel canale"),
            (RECORD, "Messaggio su un record seguito")]
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifiche_discuss")
    tipo = models.CharField("tipo", max_length=10, choices=TIPI)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+")
    messaggio = models.ForeignKey(Messaggio, on_delete=models.CASCADE, null=True, blank=True, related_name="notifiche")
    messaggio_chatter = models.ForeignKey("core.Messaggio", on_delete=models.CASCADE, null=True, blank=True,
                                          related_name="+")
    titolo = models.CharField("titolo", max_length=200)
    testo = models.TextField("anteprima", blank=True)
    url = models.CharField("link", max_length=300)
    letta = models.BooleanField("letta", default=False)
    email_inviata = models.BooleanField("email inviata", default=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)

    class Meta:
        verbose_name = "notifica"
        verbose_name_plural = "notifiche"
        ordering = ["-creata", "-pk"]
        indexes = [models.Index(fields=["utente", "letta"])]
