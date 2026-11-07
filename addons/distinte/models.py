import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum

from banca.models import iban_valido, normalizza_iban
from core.mixins import AziendaMixin

from .testo import id_creditore_valido


def _controlla_iban(obj, campo="iban"):
    setattr(obj, campo, normalizza_iban(getattr(obj, campo)))
    if getattr(obj, campo) and not iban_valido(getattr(obj, campo)):
        raise ValidationError({campo: "Questo IBAN non è valido: controlla di averlo scritto giusto."})


class CoordinateBancarie(models.Model):
    """Il conto del cliente o del fornitore: serve per i bonifici, per la banca domiciliataria delle RiBa e come IBAN
    proposto nei mandati SDD."""
    contatto = models.OneToOneField("contatti.Contatto", on_delete=models.CASCADE, related_name="coordinate_bancarie",
                                    verbose_name="contatto")
    iban = models.CharField("IBAN", max_length=34)
    bic = models.CharField("BIC", max_length=11, blank=True)
    banca = models.CharField("banca", max_length=80, blank=True, help_text="es. Banca di Credito Cooperativo, filiale di Roma")

    class Meta:
        verbose_name = "coordinate bancarie"
        verbose_name_plural = "coordinate bancarie"

    def __str__(self):
        return f"{self.contatto}: {self.iban}"

    def clean(self):
        _controlla_iban(self)

    @property
    def abi(self):
        return self.iban[5:10] if self.iban.startswith("IT") else ""

    @property
    def cab(self):
        return self.iban[10:15] if self.iban.startswith("IT") else ""


class Mandato(AziendaMixin):
    """Il mandato SEPA firmato dal cliente: autorizza l'addebito diretto sul suo conto."""
    CORE, B2B = "CORE", "B2B"
    contatto = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="mandati_sdd", verbose_name="cliente")
    riferimento = models.CharField("riferimento del mandato", max_length=35, help_text="codice univoco del mandato (UMR)")
    iban = models.CharField("IBAN del cliente", max_length=34)
    bic = models.CharField("BIC", max_length=11, blank=True)
    data_firma = models.DateField("firmato il")
    schema = models.CharField("schema", max_length=4, choices=[(CORE, "CORE (consumatori e imprese)"), (B2B, "B2B (solo imprese)")],
                              default=CORE)
    attivo = models.BooleanField("attivo", default=True)
    revocato_il = models.DateField("revocato il", null=True, blank=True)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "mandato SDD"
        verbose_name_plural = "mandati SDD"
        ordering = ["contatto__nome", "-data_firma"]
        constraints = [models.UniqueConstraint(fields=["azienda", "riferimento"], name="distinte_mandato_unico")]

    def __str__(self):
        return f"{self.riferimento} · {self.contatto}"

    def clean(self):
        _controlla_iban(self)
        if self.riferimento and not re.fullmatch(r"[A-Za-z0-9+?/\-:().,' ]{1,35}", self.riferimento):
            raise ValidationError({"riferimento": "Usa solo lettere, numeri e i segni + ? / - : ( ) . , ' (massimo 35)."})
        if self.revocato_il:
            self.attivo = False


class ConfigConto(models.Model):
    """Quello che serve sul conto dell'azienda per presentare le distinte."""
    ISO_2019, ISO_2009 = "2019", "2009"
    conto = models.OneToOneField("banca.Conto", on_delete=models.CASCADE, related_name="config_distinte", verbose_name="conto")
    codice_sia = models.CharField("codice SIA", max_length=5, blank=True, help_text="5 caratteri, lo dà la banca: serve per le RiBa")
    id_creditore = models.CharField("identificativo del creditore SEPA", max_length=35, blank=True,
                                    help_text="es. IT66ZZZ0123456789: serve per gli addebiti SDD, lo dà la banca")
    versione_sepa = models.CharField("versione dei file SEPA", max_length=4, default=ISO_2019,
                                     choices=[(ISO_2019, "ISO 20022 2019 (pain.001.001.09, pain.008.001.08)"),
                                              (ISO_2009, "ISO 20022 2009 (pain.001.001.03, pain.008.001.02)")],
                                     help_text="la più recente va bene quasi ovunque; la 2009 per le banche che non l'accettano ancora")

    class Meta:
        verbose_name = "impostazioni del conto per le distinte"
        verbose_name_plural = "impostazioni dei conti per le distinte"

    def __str__(self):
        return f"Distinte · {self.conto}"

    def clean(self):
        self.codice_sia = self.codice_sia.strip().upper()
        self.id_creditore = self.id_creditore.replace(" ", "").upper()
        if self.codice_sia and not re.fullmatch(r"[A-Z0-9]{5}", self.codice_sia):
            raise ValidationError({"codice_sia": "Il codice SIA ha 5 lettere o cifre."})
        if self.id_creditore and not id_creditore_valido(self.id_creditore):
            raise ValidationError({"id_creditore": "Identificativo del creditore non valido (controlla le cifre di controllo)."})


class Distinta(AziendaMixin):
    BONIFICI, SDD, RIBA = "bonifici", "sdd", "riba"
    TIPI = [(BONIFICI, "Bonifici SEPA ai fornitori"), (SDD, "Addebiti SDD ai clienti"), (RIBA, "Ricevute bancarie (RiBa)")]
    BOZZA, PRESENTATA, CHIUSA = "bozza", "presentata", "chiusa"
    STATI = [(BOZZA, "Da presentare"), (PRESENTATA, "Presentata alla banca"), (CHIUSA, "Chiusa")]
    tipo = models.CharField("tipo", max_length=10, choices=TIPI)
    conto = models.ForeignKey("banca.Conto", on_delete=models.PROTECT, related_name="distinte", verbose_name="conto")
    data = models.DateField("data", help_text="esecuzione dei bonifici o addebito SDD; per le RiBa la data di presentazione")
    stato = models.CharField("stato", max_length=10, choices=STATI, default=BOZZA)
    identificativo = models.CharField("identificativo del file", max_length=35, blank=True)
    presentata_il = models.DateField("presentata il", null=True, blank=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name="creata da")
    creata = models.DateTimeField("creata il", auto_now_add=True)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "distinta"
        verbose_name_plural = "distinte"
        ordering = ["-creata", "-pk"]

    def __str__(self):
        return f"Distinta {self.pk} · {self.get_tipo_display()} del {self.data:%d/%m/%Y}"

    @property
    def totale(self):
        return self.voci.aggregate(t=Sum("importo"))["t"] or 0

    @property
    def attiva(self):
        """Incassi dai clienti (SDD e RiBa); i bonifici sono pagamenti ai fornitori."""
        return self.tipo != self.BONIFICI


class VoceDistinta(models.Model):
    ATTESA, PAGATA, INSOLUTA = "attesa", "pagata", "insoluta"
    ESITI = [(ATTESA, "In attesa"), (PAGATA, "Pagata"), (INSOLUTA, "Insoluta o respinta")]
    distinta = models.ForeignKey(Distinta, on_delete=models.CASCADE, related_name="voci", verbose_name="distinta")
    scadenza = models.ForeignKey("fatturazione.Scadenza", on_delete=models.PROTECT, null=True, blank=True, related_name="voci_distinta",
                                 verbose_name="scadenza")
    scadenza_passiva = models.ForeignKey("sdi.ScadenzaPassiva", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="voci_distinta", verbose_name="scadenza da pagare")
    mandato = models.ForeignKey(Mandato, on_delete=models.PROTECT, null=True, blank=True, related_name="voci", verbose_name="mandato")
    nome = models.CharField("nome", max_length=140)
    iban = models.CharField("IBAN", max_length=34)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2)
    data = models.DateField("scadenza")
    causale = models.CharField("causale", max_length=140)
    esito = models.CharField("esito", max_length=10, choices=ESITI, default=ATTESA)
    esito_il = models.DateField("esito il", null=True, blank=True)
    motivo = models.CharField("motivo", max_length=120, blank=True)
    incasso = models.OneToOneField("fatturazione.Incasso", on_delete=models.SET_NULL, null=True, blank=True, related_name="voce_distinta",
                                   verbose_name="incasso")

    class Meta:
        verbose_name = "voce della distinta"
        verbose_name_plural = "voci della distinta"
        ordering = ["data", "pk"]

    def __str__(self):
        return f"{self.nome} · {self.importo} €"

    @property
    def fattura(self):
        return self.scadenza.fattura if self.scadenza_id else (self.scadenza_passiva.fattura if self.scadenza_passiva_id else None)
