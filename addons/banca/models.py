from decimal import Decimal

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum

from core.mixins import AziendaMixin


def iban_valido(iban):
    if not iban[:2].isalpha() or not iban[2:4].isdigit() or not iban.isalnum() or not 15 <= len(iban) <= 34:
        return False
    numeri = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(numeri) % 97 == 1


def normalizza_iban(iban):
    return "".join((iban or "").split()).upper()


class Conto(AziendaMixin):
    nome = models.CharField("nome", max_length=80, help_text="es. Conto principale")
    iban = models.CharField("IBAN", max_length=34)
    banca = models.CharField("banca", max_length=80, blank=True)
    bic = models.CharField("BIC", max_length=11, blank=True)
    attivo = models.BooleanField("attivo", default=True)
    saldo = models.DecimalField("ultimo saldo dalla banca", max_digits=14, decimal_places=2, null=True, blank=True, editable=False)
    saldo_al = models.DateField("saldo al", null=True, blank=True, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "conto"
        verbose_name_plural = "conti"
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=["azienda", "iban"], name="banca_conto_unico")]

    def __str__(self):
        return self.nome

    @property
    def collegamento_o_niente(self):
        try:
            return self.collegamento
        except models.ObjectDoesNotExist:
            return None

    def clean(self):
        self.iban = normalizza_iban(self.iban)
        if self.iban and not iban_valido(self.iban):
            raise ValidationError({"iban": "Questo IBAN non è valido: controlla di averlo scritto giusto."})


class Importazione(AziendaMixin):
    conto = models.ForeignKey(Conto, on_delete=models.CASCADE, related_name="importazioni", verbose_name="conto")
    nome_file = models.CharField("file", max_length=200)
    formato = models.CharField("formato", max_length=10)
    nuovi = models.PositiveIntegerField("movimenti nuovi", default=0)
    doppi = models.PositiveIntegerField("già presenti", default=0)
    scartati = models.PositiveIntegerField("righe non lette", default=0)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="importato da")
    creata = models.DateTimeField("importato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "importazione"
        verbose_name_plural = "importazioni"
        ordering = ["-creata"]

    def __str__(self):
        return f"{self.nome_file} ({self.creata:%d/%m/%Y})"


class MovimentoBanca(AziendaMixin):
    DA_ABBINARE, PARZIALE, ABBINATO, IGNORATO = "da_abbinare", "parziale", "abbinato", "ignorato"
    STATI = [(DA_ABBINARE, "Da abbinare"), (PARZIALE, "Abbinato in parte"), (ABBINATO, "Abbinato"), (IGNORATO, "Ignorato")]
    conto = models.ForeignKey(Conto, on_delete=models.CASCADE, related_name="movimenti", verbose_name="conto")
    importazione = models.ForeignKey(Importazione, on_delete=models.SET_NULL, null=True, blank=True, related_name="movimenti", verbose_name="importazione")
    data = models.DateField("data")
    valuta = models.DateField("valuta", null=True, blank=True)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, help_text="positivo se entra, negativo se esce")
    descrizione = models.TextField("descrizione", blank=True)
    controparte = models.CharField("controparte", max_length=200, blank=True)
    iban_controparte = models.CharField("IBAN controparte", max_length=34, blank=True)
    riferimento = models.CharField("riferimento della banca", max_length=120, blank=True)
    impronta = models.CharField("impronta", max_length=64, editable=False)
    stato = models.CharField("stato", max_length=12, choices=STATI, default=DA_ABBINARE, editable=False, db_index=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "movimento"
        verbose_name_plural = "movimenti"
        ordering = ["-data", "-pk"]
        constraints = [models.UniqueConstraint(fields=["conto", "impronta"], name="banca_movimento_unico")]

    def __str__(self):
        return f"{self.data:%d/%m/%Y} · {self.importo} €"

    @property
    def abbinato(self):
        return self.abbinamenti.aggregate(t=Sum("importo"))["t"] or Decimal(0)

    @property
    def da_coprire(self):
        """Quanto resta, sempre positivo: gli importi di un'uscita si contano in valore assoluto."""
        return abs(self.importo) - self.abbinato


class Abbinamento(models.Model):
    """Un pezzo di movimento su una scadenza. L'incasso è quello vero di Fatturazione: annullandolo là, l'abbinamento sparisce."""
    movimento = models.ForeignKey(MovimentoBanca, on_delete=models.CASCADE, related_name="abbinamenti", verbose_name="movimento")
    incasso = models.OneToOneField("fatturazione.Incasso", on_delete=models.CASCADE, null=True, blank=True, related_name="da_banca", verbose_name="incasso")
    scadenza_passiva = models.ForeignKey("sdi.ScadenzaPassiva", on_delete=models.CASCADE, null=True, blank=True, related_name="da_banca", verbose_name="scadenza da pagare")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2)
    # un altro documento che il movimento salda (il rimborso di una nota spese…): la banca non dipende dai moduli
    tipo_documento = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE, null=True, blank=True,
                                       related_name="+", verbose_name="tipo di documento")
    id_documento = models.PositiveBigIntegerField("documento", null=True, blank=True)
    documento = GenericForeignKey("tipo_documento", "id_documento")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="abbinato da")
    creato = models.DateTimeField("abbinato il", auto_now_add=True)

    class Meta:
        verbose_name = "abbinamento"
        verbose_name_plural = "abbinamenti"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.movimento}: {self.importo} €"


class Aggregatore(AziendaMixin):
    """Il servizio PSD2 che legge i conti al posto nostro (con il consenso del titolare, banca per banca).
    Le chiavi si scrivono e si salvano cifrate, non si rileggono."""
    GOCARDLESS, FINTO = "gocardless", "finto"
    TIPI = [(GOCARDLESS, "GoCardless Bank Account Data"), (FINTO, "Simulato (prove e demo)")]
    nome = models.CharField("nome", max_length=80, default="GoCardless")
    tipo = models.CharField("servizio", max_length=12, choices=TIPI, default=GOCARDLESS)
    secret_id = models.CharField("Secret ID", max_length=200, blank=True)
    secret_key_cifrata = models.TextField(blank=True, editable=False)
    attivo = models.BooleanField("attivo", default=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "servizio di lettura dei conti"
        verbose_name_plural = "servizi di lettura dei conti"
        ordering = ["pk"]

    def __str__(self):
        return self.nome

    def secret_key(self):
        from core import cifratura
        return cifratura.decifra(self.secret_key_cifrata) if self.secret_key_cifrata else ""


class CollegamentoConto(AziendaMixin):
    """Il conto letto in automatico: il titolare dà il consenso sul sito della banca, poi i movimenti arrivano da soli
    finché il consenso vale (di solito 90 o 180 giorni), poi va rinnovato."""
    IN_ATTESA, ATTIVO, SCADUTO, ERRORE = "in_attesa", "attivo", "scaduto", "errore"
    STATI = [(IN_ATTESA, "In attesa del consenso"), (ATTIVO, "Attivo"), (SCADUTO, "Consenso scaduto"), (ERRORE, "Errore")]
    conto = models.OneToOneField(Conto, on_delete=models.CASCADE, related_name="collegamento", verbose_name="conto")
    aggregatore = models.ForeignKey(Aggregatore, on_delete=models.CASCADE, related_name="collegamenti", verbose_name="servizio")
    istituto = models.CharField("banca", max_length=120, help_text="il codice della banca presso il servizio")
    nome_istituto = models.CharField("nome della banca", max_length=200, blank=True)
    richiesta = models.CharField("richiesta di consenso", max_length=120, blank=True)
    link_consenso = models.URLField("pagina del consenso", max_length=1000, blank=True)
    conto_esterno = models.CharField("conto presso il servizio", max_length=120, blank=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=IN_ATTESA)
    scade_il = models.DateField("consenso valido fino al", null=True, blank=True)
    giorni_storico = models.PositiveSmallIntegerField("giorni di storico", default=90)
    ultima_lettura = models.DateTimeField("ultima lettura", null=True, blank=True)
    letto_fino_al = models.DateField("movimenti letti fino al", null=True, blank=True)
    errore = models.CharField("ultimo errore", max_length=300, blank=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name="collegato da")
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "collegamento del conto"
        verbose_name_plural = "collegamenti dei conti"

    def __str__(self):
        return f"{self.conto} · {self.nome_istituto or self.istituto}"
