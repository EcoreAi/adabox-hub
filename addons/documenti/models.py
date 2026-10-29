import secrets
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin
from core.storage import StoragePrivato


class Spazio(AziendaMixin):
    """Spazio di lavoro: personale (di un utente) o condiviso (tra i membri). Le sue cartelle seguono le regole dello
    spazio; le cartelle senza spazio sono l'archivio aziendale."""
    PERSONALE, CONDIVISO = "personale", "condiviso"
    TIPI = [(PERSONALE, "Personale"), (CONDIVISO, "Condiviso")]
    nome = models.CharField("nome", max_length=120)
    tipo = models.CharField("tipo", max_length=10, choices=TIPI, default=PERSONALE)
    proprietario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="spazi_documenti",
                                     verbose_name="proprietario")
    descrizione = models.TextField("descrizione", blank=True)
    quota_mb = models.PositiveIntegerField("quota (MB)", default=0,
                                           help_text="solo per gli spazi condivisi; 0 = solo la quota dell'azienda")
    membri = models.ManyToManyField(settings.AUTH_USER_MODEL, through="MembroSpazio", blank=True, related_name="+",
                                    verbose_name="membri")
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "spazio di lavoro"
        verbose_name_plural = "spazi di lavoro"
        ordering = ["tipo", "nome", "pk"]
        permissions = [("crea_spazio_condiviso", "Crea spazi condivisi")]

    def __str__(self):
        return self.nome

    @property
    def personale(self):
        return self.tipo == self.PERSONALE


class MembroSpazio(models.Model):
    LETTURA, SCRITTURA, GESTIONE = "lettura", "scrittura", "gestione"
    RUOLI = [(LETTURA, "Legge"), (SCRITTURA, "Legge e scrive"), (GESTIONE, "Gestisce (anche i membri)")]
    spazio = models.ForeignKey(Spazio, on_delete=models.CASCADE, related_name="iscritti", verbose_name="spazio")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+",
                               verbose_name="utente")
    ruolo = models.CharField("ruolo", max_length=10, choices=RUOLI, default=SCRITTURA)

    class Meta:
        verbose_name = "membro"
        verbose_name_plural = "membri"
        constraints = [models.UniqueConstraint(fields=["spazio", "utente"], name="documenti_membro_unico")]

    def __str__(self):
        return f"{self.utente} · {self.get_ruolo_display()}"


class QuotaUtente(AziendaMixin):
    """Quanti MB può occupare un utente con i suoi spazi personali (senza riga: il default dell'azienda)."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+",
                               verbose_name="utente")
    quota_mb = models.PositiveIntegerField("quota (MB)", help_text="0 = solo la quota dell'azienda")

    class Meta(AziendaMixin.Meta):
        verbose_name = "quota di un utente"
        verbose_name_plural = "quote degli utenti"
        constraints = [models.UniqueConstraint(fields=["azienda", "utente"], name="documenti_quota_unica")]

    def __str__(self):
        return f"{self.utente}: {self.quota_mb} MB"


class Cartella(AziendaMixin):
    """Cartella dell'archivio. I gruppi vuoti ereditano quelli della cartella madre (in cima: tutti gli utenti).
    Le cartelle di uno spazio di lavoro seguono invece le regole dello spazio."""
    nome = models.CharField("nome", max_length=120)
    padre = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="figlie",
                              verbose_name="dentro a")
    descrizione = models.TextField("descrizione", blank=True)
    gruppi_lettura = models.ManyToManyField("auth.Group", blank=True, related_name="+", verbose_name="chi la vede",
                                            help_text="vuoto: come la cartella madre (in cima: tutti)")
    gruppi_scrittura = models.ManyToManyField("auth.Group", blank=True, related_name="+",
                                              verbose_name="chi ci carica e modifica",
                                              help_text="vuoto: come la cartella madre (in cima: chi la vede)")
    modello = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name="raccoglie gli allegati di",
                                help_text="gli allegati caricati sui record di questo tipo finiscono qui")
    spazio = models.ForeignKey(Spazio, on_delete=models.CASCADE, null=True, blank=True, related_name="cartelle",
                               verbose_name="spazio di lavoro", help_text="vuoto = archivio aziendale")

    class Meta(AziendaMixin.Meta):
        verbose_name = "cartella"
        verbose_name_plural = "cartelle"
        ordering = ["nome", "pk"]
        permissions = [("vedi_tutte_cartelle", "Vede e modifica tutte le cartelle")]

    def __str__(self):
        return self.percorso()

    def percorso(self):
        parti, c, visti = [], self, set()
        while c is not None and c.pk not in visti:
            visti.add(c.pk)
            parti.append(c.nome)
            c = c.padre
        return " / ".join(reversed(parti))

    def save(self, *args, **kwargs):
        if self.padre_id is not None:                  # una sottocartella sta nello spazio della madre
            self.spazio_id = Cartella.objects.filter(pk=self.padre_id).values_list("spazio_id", flat=True).first()
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError
        c = self.padre
        while c is not None:
            if c.pk == self.pk:
                raise ValidationError({"padre": "Una cartella non può stare dentro a sé stessa."})
            c = c.padre


class Tag(models.Model):
    nome = models.CharField("nome", max_length=60, unique=True)
    colore = models.CharField("colore", max_length=7, default="#1e3a8a")

    class Meta:
        verbose_name = "tag"
        verbose_name_plural = "tag"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


def _percorso_documento(instance, filename):
    return f"documenti/{timezone.now():%Y/%m}/{uuid.uuid4().hex}-{filename}"


class Documento(AziendaMixin, ProprietaMixin):
    cartella = models.ForeignKey(Cartella, on_delete=models.PROTECT, related_name="documenti", verbose_name="cartella")
    nome = models.CharField("nome", max_length=200)
    file = models.FileField("file", upload_to=_percorso_documento, storage=StoragePrivato(), max_length=300, blank=True)
    allegato = models.ForeignKey("core.Allegato", on_delete=models.CASCADE, null=True, blank=True, related_name="+",
                                 verbose_name="allegato", help_text="documento che rimanda a un allegato di un record")
    mime = models.CharField("tipo", max_length=100, blank=True)
    dimensione = models.PositiveBigIntegerField("dimensione", default=0)
    descrizione = models.TextField("descrizione", blank=True)
    tag = models.ManyToManyField(Tag, blank=True, related_name="documenti", verbose_name="tag")
    proprietario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="proprietario")
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    record = GenericForeignKey("content_type", "object_id")
    bloccato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="bloccato da")
    cestinato_il = models.DateTimeField("nel cestino dal", null=True, blank=True)
    versione = models.PositiveIntegerField("versione", default=1)
    caricato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="ultima versione di")
    creato = models.DateTimeField("caricato il", auto_now_add=True)
    modificato = models.DateTimeField("modificato il", auto_now=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "documento"
        verbose_name_plural = "documenti"
        ordering = ["-creato", "-pk"]
        indexes = [models.Index(fields=["content_type", "object_id"]), models.Index(fields=["cartella", "cestinato_il"])]

    def __str__(self):
        return self.nome

    @property
    def contenuto(self):
        """Il FileField con i byte: quello del documento o quello dell'allegato a cui rimanda."""
        return self.allegato.file if self.allegato_id else self.file

    @property
    def immagine(self):
        return self.mime.startswith("image/")

    @property
    def pdf(self):
        return self.mime == "application/pdf"

    @property
    def estensione(self):
        return self.nome.rsplit(".", 1)[-1].upper()[:5] if "." in self.nome else "FILE"


def _percorso_versione(instance, filename):
    return f"documenti/versioni/{timezone.now():%Y/%m}/{uuid.uuid4().hex}-{filename}"


class Versione(models.Model):
    """Una versione precedente di un documento: salvare un file con lo stesso nome nella stessa cartella crea una
    versione nuova e la vecchia finisce qui (si tengono le ultime, secondo le impostazioni dell'azienda)."""
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, related_name="versioni",
                                  verbose_name="documento")
    numero = models.PositiveIntegerField("versione")
    file = models.FileField("file", upload_to=_percorso_versione, storage=StoragePrivato(), max_length=300)
    dimensione = models.PositiveBigIntegerField("dimensione", default=0)
    caricata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="caricata da")
    creata = models.DateTimeField("del")

    class Meta:
        verbose_name = "versione"
        verbose_name_plural = "versioni"
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["documento", "numero"], name="documenti_versione_unica")]

    def __str__(self):
        return f"{self.documento} v{self.numero}"


def _token():
    return secrets.token_urlsafe(24)


class Condivisione(AziendaMixin):
    """Link pubblico (senza login) a una cartella o ad alcuni documenti, con scadenza."""
    nome = models.CharField("nome", max_length=120, help_text="per riconoscerla, es. «Documenti per il notaio»")
    token = models.CharField("token", max_length=64, unique=True, default=_token, editable=False)
    cartella = models.ForeignKey(Cartella, on_delete=models.CASCADE, null=True, blank=True, related_name="condivisioni",
                                 verbose_name="cartella")
    documenti = models.ManyToManyField(Documento, blank=True, related_name="condivisioni", verbose_name="documenti")
    scadenza = models.DateField("scade il")
    consente_caricamento = models.BooleanField("chi ha il link può caricare file", default=False)
    creata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="creata da", editable=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)
    revocata = models.BooleanField("revocata", default=False, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "condivisione"
        verbose_name_plural = "condivisioni"
        ordering = ["-creata", "-pk"]

    def __str__(self):
        return self.nome

    @property
    def attiva(self):
        return not self.revocata and self.scadenza >= timezone.localdate()


class AccessoCondivisione(models.Model):
    condivisione = models.ForeignKey(Condivisione, on_delete=models.CASCADE, related_name="accessi")
    quando = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    azione = models.CharField(max_length=20)
    documento = models.ForeignKey(Documento, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "accesso a una condivisione"
        verbose_name_plural = "accessi alle condivisioni"
        ordering = ["-quando", "-pk"]


class Richiesta(AziendaMixin):
    """Richiesta di un documento a un collega: un'attività pianificata che si chiude col caricamento."""
    APERTA, COMPLETATA, ANNULLATA = "aperta", "completata", "annullata"
    STATI = [(APERTA, "Aperta"), (COMPLETATA, "Completata"), (ANNULLATA, "Annullata")]
    titolo = models.CharField("documento richiesto", max_length=160)
    descrizione = models.TextField("dettagli", blank=True)
    cartella = models.ForeignKey(Cartella, on_delete=models.PROTECT, related_name="richieste",
                                 verbose_name="dove va archiviato")
    destinatario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+",
                                     verbose_name="richiesto a")
    scadenza = models.DateField("entro il")
    stato = models.CharField("stato", max_length=10, choices=STATI, default=APERTA, editable=False)
    richiesta_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="richiesto da", editable=False)
    documento = models.ForeignKey(Documento, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                  verbose_name="documento caricato", editable=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "richiesta di documento"
        verbose_name_plural = "richieste di documenti"
        ordering = ["stato", "scadenza", "pk"]

    def __str__(self):
        return self.titolo
