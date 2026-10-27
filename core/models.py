import hashlib
import secrets
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from .storage import StoragePrivato


class Azienda(models.Model):
    nome = models.CharField("nome", max_length=160)
    partita_iva = models.CharField("partita IVA", max_length=16, blank=True)
    codice_fiscale = models.CharField("codice fiscale", max_length=16, blank=True)
    indirizzo = models.CharField("indirizzo", max_length=200, blank=True)
    cap = models.CharField("CAP", max_length=10, blank=True)
    citta = models.CharField("città", max_length=100, blank=True)
    provincia = models.CharField("provincia", max_length=2, blank=True)
    email = models.EmailField("email", blank=True)
    telefono = models.CharField("telefono", max_length=40, blank=True)
    logo = models.ImageField("logo", upload_to="aziende/", blank=True)
    attiva = models.BooleanField("attiva", default=True)

    class Meta:
        verbose_name = "azienda"
        verbose_name_plural = "aziende"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class ProfiloUtente(models.Model):
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profilo")
    aziende = models.ManyToManyField(Azienda, verbose_name="aziende consentite", blank=True)
    azienda_predefinita = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name="+", verbose_name="azienda predefinita")

    class Meta:
        verbose_name = "profilo utente"
        verbose_name_plural = "profili utente"

    def __str__(self):
        return f"profilo di {self.utente}"


class Modulo(models.Model):
    DISPONIBILE, INSTALLATO, DA_AGGIORNARE, MANCANTE, ERRORE = (
        "disponibile", "installato", "da_aggiornare", "mancante", "errore")
    STATI = [(DISPONIBILE, "Disponibile"), (INSTALLATO, "Installato"), (DA_AGGIORNARE, "Da aggiornare"),
             (MANCANTE, "Mancante"), (ERRORE, "Errore")]
    slug = models.SlugField("slug", max_length=31, unique=True)
    nome = models.CharField("nome", max_length=120)
    versione_installata = models.CharField("versione installata", max_length=20, blank=True)
    versione_disponibile = models.CharField("versione disponibile", max_length=20, blank=True)
    stato = models.CharField("stato", max_length=20, choices=STATI, default=DISPONIBILE)
    application = models.BooleanField("app", default=False)
    installato_il = models.DateTimeField("installato il", null=True, blank=True)
    aggiornato_il = models.DateTimeField("aggiornato il", null=True, blank=True)
    gruppi_creati = models.JSONField("gruppi creati", default=list, blank=True)
    ultimo_errore = models.TextField("ultimo errore", blank=True)

    class Meta:
        verbose_name = "modulo"
        verbose_name_plural = "moduli"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.slug})"


class TokenApi(models.Model):
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="token_api")
    nome = models.CharField("nome", max_length=80)
    chiave = models.CharField("chiave (hash)", max_length=64, unique=True, editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    ultimo_uso = models.DateTimeField("ultimo uso", null=True, blank=True)
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "token API"
        verbose_name_plural = "token API"
        ordering = ["-creato"]

    def __str__(self):
        return f"{self.nome} ({self.utente})"

    @staticmethod
    def _hash(chiaro):
        return hashlib.sha256(chiaro.encode()).hexdigest()

    @classmethod
    def genera(cls, utente, nome):
        chiaro = secrets.token_urlsafe(32)
        return cls.objects.create(utente=utente, nome=nome, chiave=cls._hash(chiaro)), chiaro

    @classmethod
    def verifica(cls, chiaro):
        token = (cls.objects.filter(chiave=cls._hash(chiaro), attivo=True, utente__is_active=True)
                 .select_related("utente").first())
        if token:
            cls.objects.filter(pk=token.pk).update(ultimo_uso=timezone.now())
        return token


class Lavoro(models.Model):
    """Lavoro in background: una funzione Python con argomenti JSON, eseguita dal worker."""
    IN_CODA, IN_CORSO, FATTO, FALLITO = "in_coda", "in_corso", "fatto", "fallito"
    STATI = [(IN_CODA, "In coda"), (IN_CORSO, "In corso"), (FATTO, "Fatto"), (FALLITO, "Fallito")]
    funzione = models.CharField("funzione", max_length=200)
    argomenti = models.JSONField("argomenti", default=dict, blank=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=IN_CODA)
    tentativi = models.PositiveSmallIntegerField("tentativi", default=0)
    max_tentativi = models.PositiveSmallIntegerField("tentativi massimi", default=3)
    esegui_dopo = models.DateTimeField("esegui dopo", default=timezone.now)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    iniziato = models.DateTimeField("iniziato il", null=True, blank=True)
    finito = models.DateTimeField("finito il", null=True, blank=True)
    errore = models.TextField("errore", blank=True)
    risultato = models.TextField("risultato", blank=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="azienda")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+", verbose_name="utente")

    class Meta:
        verbose_name = "lavoro"
        verbose_name_plural = "lavori"
        ordering = ["-creato", "-pk"]
        indexes = [models.Index(fields=["stato", "esegui_dopo"])]

    def __str__(self):
        return f"{self.funzione} #{self.pk}"


class Pianificazione(models.Model):
    """Lavoro ricorrente dichiarato nel manifest di un modulo (o dal kernel): il worker lo accoda quando scade."""
    modulo = models.CharField("modulo", max_length=31)
    nome = models.CharField("nome", max_length=120)
    funzione = models.CharField("funzione", max_length=200)
    ogni = models.CharField("ogni", max_length=10, help_text="15m, 1h, 1d…")
    alle = models.CharField("alle", max_length=5, blank=True, help_text="HH:MM, solo per gli intervalli in giorni")
    attiva = models.BooleanField("attiva", default=True)
    prossima_esecuzione = models.DateTimeField("prossima esecuzione", null=True, blank=True)
    ultima_esecuzione = models.DateTimeField("ultima esecuzione", null=True, blank=True)

    class Meta:
        verbose_name = "pianificazione"
        verbose_name_plural = "pianificazioni"
        ordering = ["modulo", "nome"]
        constraints = [models.UniqueConstraint(fields=["modulo", "nome"], name="pianificazione_unica")]

    def __str__(self):
        return f"{self.modulo}: {self.nome}"


class Parametro(models.Model):
    """Valore di un'impostazione dichiarata nel manifest (`settings`): globale o per azienda."""
    chiave = models.CharField("chiave", max_length=100, help_text="<modulo>.<nome>")
    valore = models.JSONField("valore", null=True, blank=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.CASCADE, null=True, blank=True, verbose_name="azienda")

    class Meta:
        verbose_name = "parametro"
        verbose_name_plural = "parametri"
        ordering = ["chiave"]
        constraints = [
            models.UniqueConstraint(fields=["chiave"], condition=models.Q(azienda__isnull=True),
                                    name="parametro_globale_unico"),
            models.UniqueConstraint(fields=["chiave", "azienda"], condition=models.Q(azienda__isnull=False),
                                    name="parametro_azienda_unico"),
        ]

    def __str__(self):
        return f"{self.chiave} = {self.valore!r}" + (f" ({self.azienda})" if self.azienda_id else "")


class Sequenza(models.Model):
    """Numerazione progressiva (es. ATT/2026/0001), per azienda o globale (azienda vuota)."""
    MAI, ANNO = "mai", "anno"
    codice = models.CharField("codice", max_length=100, help_text="<modulo>.<nome>")
    azienda = models.ForeignKey(Azienda, on_delete=models.CASCADE, null=True, blank=True, verbose_name="azienda")
    formato = models.CharField("formato", max_length=100, help_text="{anno} {mese:02d} {numero:05d}")
    prossimo = models.PositiveIntegerField("prossimo numero", default=1)
    azzera = models.CharField("azzera", max_length=4, choices=[(MAI, "Mai"), (ANNO, "Ogni anno")], default=MAI)
    anno = models.PositiveSmallIntegerField("anno corrente", null=True, blank=True)

    class Meta:
        verbose_name = "sequenza"
        verbose_name_plural = "sequenze"
        ordering = ["codice"]
        constraints = [
            models.UniqueConstraint(fields=["codice"], condition=models.Q(azienda__isnull=True),
                                    name="sequenza_globale_unica"),
            models.UniqueConstraint(fields=["codice", "azienda"], condition=models.Q(azienda__isnull=False),
                                    name="sequenza_azienda_unica"),
        ]

    def __str__(self):
        return f"{self.codice}" + (f" ({self.azienda})" if self.azienda_id else "")


def _percorso_allegato(instance, filename):
    return f"allegati/{timezone.now():%Y/%m}/{uuid.uuid4().hex}-{filename}"


class Allegato(models.Model):
    """File allegato a un record qualsiasi; privato: si scarica solo con il permesso di vedere il record."""
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    file = models.FileField("file", upload_to=_percorso_allegato, storage=StoragePrivato(), max_length=300)
    nome = models.CharField("nome", max_length=200)
    mime = models.CharField("tipo", max_length=100, blank=True)
    dimensione = models.PositiveBigIntegerField("dimensione", default=0)
    caricato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="caricato da")
    creato = models.DateTimeField("caricato il", auto_now_add=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="azienda")

    class Meta:
        verbose_name = "allegato"
        verbose_name_plural = "allegati"
        ordering = ["-creato", "-pk"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return self.nome


class Messaggio(models.Model):
    """Voce del chatter di un record: nota interna, messaggio ai follower, tracciamento, evento di sistema."""
    NOTA, MESSAGGIO, TRACCIAMENTO, SISTEMA = "nota", "messaggio", "tracciamento", "sistema"
    TIPI = [(NOTA, "Nota"), (MESSAGGIO, "Messaggio"), (TRACCIAMENTO, "Tracciamento"), (SISTEMA, "Sistema")]
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    tipo = models.CharField("tipo", max_length=12, choices=TIPI, default=MESSAGGIO)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+", verbose_name="autore")
    corpo = models.TextField("testo", blank=True)
    modifiche = models.JSONField("modifiche", default=list, blank=True)
    allegati = models.ManyToManyField(Allegato, blank=True, related_name="messaggi", verbose_name="allegati")
    message_id = models.CharField("Message-ID", max_length=255, blank=True, db_index=True)
    creato = models.DateTimeField("creato il", default=timezone.now)

    class Meta:
        verbose_name = "messaggio"
        verbose_name_plural = "messaggi"
        ordering = ["-creato", "-pk"]
        indexes = [models.Index(fields=["content_type", "object_id", "-creato"])]

    def __str__(self):
        return f"{self.get_tipo_display()} di {self.autore or 'sistema'} ({self.creato:%d/%m/%Y %H:%M})"


class Follower(models.Model):
    """Chi segue un record: riceve per email i messaggi (non le note)."""
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="segue")

    class Meta:
        verbose_name = "follower"
        verbose_name_plural = "follower"
        constraints = [models.UniqueConstraint(fields=["content_type", "object_id", "utente"], name="follower_unico")]

    def __str__(self):
        return f"{self.utente} segue {self.content_type.model} #{self.object_id}"


class EmailRicevuta(models.Model):
    """Email arrivata nella casella delle risposte: esito dell'abbinamento a un record del chatter."""
    ABBINATA, NON_ABBINATA, RIFIUTATA, ERRORE = "abbinata", "non_abbinata", "rifiutata", "errore"
    STATI = [(ABBINATA, "Abbinata"), (NON_ABBINATA, "Non abbinata"), (RIFIUTATA, "Rifiutata"), (ERRORE, "Errore")]
    message_id = models.CharField("Message-ID", max_length=255, unique=True)
    mittente = models.CharField("mittente", max_length=254, blank=True)
    oggetto = models.CharField("oggetto", max_length=255, blank=True)
    ricevuta = models.DateTimeField("ricevuta il", auto_now_add=True)
    stato = models.CharField("stato", max_length=12, choices=STATI)
    motivo = models.TextField("motivo", blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    messaggio = models.ForeignKey(Messaggio, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="messaggio")

    class Meta:
        verbose_name = "email ricevuta"
        verbose_name_plural = "email ricevute"
        ordering = ["-ricevuta", "-pk"]

    def __str__(self):
        return f"{self.oggetto or '(senza oggetto)'} da {self.mittente}"
