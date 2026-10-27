import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


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
