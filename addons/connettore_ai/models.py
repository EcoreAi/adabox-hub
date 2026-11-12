"""Chi ha collegato quale chat esterna, con quali token, e che cosa ha chiesto.

I segreti (codici, token, segreti dei client) non si salvano: resta solo l'impronta SHA-256, come per i token dell'API.
I client e i codici sono dell'istanza; collegamenti e chiamate sono di un'azienda."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin

FORNITORI = [("claude", "Claude"), ("chatgpt", "ChatGPT"), ("gemini", "Gemini"), ("mistral", "Le Chat (Mistral)"),
             ("locale", "Programma sul computer"), ("altro", "Altro")]


class ClientOAuth(models.Model):
    """Una chat esterna che può collegarsi. Si presenta con un documento pubblico al suo indirizzo (CIMD: il `client_id`
    è quell'indirizzo), registrandosi da sé (DCR: il `client_id` glielo diamo noi) o con le credenziali che un
    amministratore ha creato qui e copiato nella console del fornitore."""
    CIMD, DCR, A_MANO = "cimd", "dcr", "mano"
    TIPI = [(CIMD, "Documento pubblico"), (DCR, "Registrata da sé"), (A_MANO, "Credenziali create a mano")]
    client_id = models.CharField("identificativo", max_length=500, unique=True)
    tipo = models.CharField("tipo", max_length=4, choices=TIPI)
    nome = models.CharField("nome dichiarato", max_length=120, blank=True)
    fornitore = models.CharField("fornitore", max_length=20, choices=FORNITORI, default="altro")
    redirect_uris = models.JSONField("indirizzi di ritorno", default=list)
    autenticazione = models.CharField("autenticazione", max_length=24, default="none", help_text="none = client pubblico, con il solo PKCE")
    impronta = models.CharField("impronta del segreto", max_length=64, blank=True, editable=False)
    creato = models.DateTimeField("vista la prima volta", auto_now_add=True)
    letto = models.DateTimeField("documento letto il", null=True, blank=True)
    ultimo_uso = models.DateTimeField("ultimo uso", null=True, blank=True)

    class Meta:
        verbose_name = "chat conosciuta"
        verbose_name_plural = "chat conosciute"
        ordering = ["-creato"]

    def __str__(self):
        return self.nome or self.get_fornitore_display()


class ChatCollegata(AziendaMixin):
    """Il permesso che una persona ha dato a una chat esterna di leggere adabox a suo nome, in un'azienda. Restringe
    ciò che la persona può fare, non lo allarga mai: a ogni chiamata valgono i suoi permessi del momento."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="collegamenti_ai",
                               verbose_name="persona")
    client = models.ForeignKey(ClientOAuth, on_delete=models.CASCADE, related_name="collegamenti", verbose_name="chat")
    fornitore = models.CharField("fornitore", max_length=20, choices=FORNITORI, default="altro")
    app = models.JSONField("solo queste app", default=list, blank=True, help_text="vuoto = tutte quelle che la persona vede")
    sola_lettura = models.BooleanField("sola lettura", default=True)
    segnaposto = models.JSONField("segnaposto dei dati personali", default=dict, blank=True, editable=False)
    creato = models.DateTimeField("collegata il", auto_now_add=True)
    ultimo_uso = models.DateTimeField("ultimo uso", null=True, blank=True)
    revocato = models.DateTimeField("scollegata il", null=True, blank=True)
    revocato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                    verbose_name="scollegata da")

    class Meta(AziendaMixin.Meta):
        verbose_name = "collegamento"
        verbose_name_plural = "collegamenti"
        ordering = ["-creato"]

    def __str__(self):
        return f"{self.get_fornitore_display()} di {self.utente}"

    @property
    def attivo(self):
        return self.revocato is None

    def revoca(self, da=None):
        """Da questo momento nessun token del collegamento vale più."""
        if self.revocato is None:
            self.revocato, self.revocato_da = timezone.now(), da
            self.save(update_fields=["revocato", "revocato_da"])
        self.token.all().delete()


class Codice(models.Model):
    """Il codice di autorizzazione: vale una volta, per pochi minuti, solo per chi conosce il verificatore PKCE."""
    impronta = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(ClientOAuth, on_delete=models.CASCADE, related_name="+")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, related_name="+")
    redirect_uri = models.CharField(max_length=600)
    sfida = models.CharField(max_length=64)
    app = models.JSONField(default=list, blank=True)
    scade = models.DateTimeField()
    usato = models.DateTimeField(null=True, blank=True)
    collegamento = models.ForeignKey(ChatCollegata, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "codice di autorizzazione"
        verbose_name_plural = "codici di autorizzazione"


class Token(models.Model):
    """Token di accesso (un'ora) e di rinnovo (ruotato a ogni uso) di un collegamento."""
    ACCESSO, RINNOVO = "accesso", "rinnovo"
    collegamento = models.ForeignKey(ChatCollegata, on_delete=models.CASCADE, related_name="token")
    tipo = models.CharField(max_length=7, choices=[(ACCESSO, "Accesso"), (RINNOVO, "Rinnovo")])
    impronta = models.CharField(max_length=64, unique=True)
    scade = models.DateTimeField()
    usato = models.DateTimeField(null=True, blank=True)
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "token"
        verbose_name_plural = "token"
        indexes = [models.Index(fields=["scade"])]


class Chiamata(AziendaMixin):
    """Registro delle chiamate arrivate dalle chat: strumento, vista, esito e durata. Mai i valori chiesti o restituiti."""
    FATTA, ERRORE, RIFIUTATA = "fatta", "errore", "rifiutata"
    ESITI = [(FATTA, "Fatta"), (ERRORE, "Errore"), (RIFIUTATA, "Rifiutata")]
    collegamento = models.ForeignKey(ChatCollegata, on_delete=models.CASCADE, related_name="chiamate", verbose_name="collegamento")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+", verbose_name="persona")
    creato = models.DateTimeField("il", auto_now_add=True, db_index=True)
    strumento = models.CharField("strumento", max_length=60)
    vista = models.CharField("vista", max_length=80, blank=True)
    esito = models.CharField("esito", max_length=10, choices=ESITI)
    motivo = models.CharField("motivo", max_length=300, blank=True)
    durata_ms = models.PositiveIntegerField("durata (ms)", default=0)
    mascherati = models.PositiveIntegerField("dati personali protetti", default=0)

    class Meta(AziendaMixin.Meta):
        verbose_name = "chiamata"
        verbose_name_plural = "chiamate"
        ordering = ["-creato", "-pk"]

    def __str__(self):
        return f"{self.strumento} ({self.get_esito_display()})"
