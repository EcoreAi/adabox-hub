from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.mixins import AziendaMixin


class Magazzino(AziendaMixin):
    nome = models.CharField("nome", max_length=80)
    indirizzo = models.CharField("indirizzo", max_length=200, blank=True)
    predefinito = models.BooleanField("predefinito", default=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "magazzino"
        verbose_name_plural = "magazzini"
        ordering = ["-predefinito", "nome"]

    def __str__(self):
        return self.nome

    @classmethod
    def predefinito_per(cls, azienda):
        m = cls.objects.filter(azienda=azienda).order_by("-predefinito", "pk").first()
        return m or cls.objects.create(azienda=azienda, nome="Magazzino principale", predefinito=True)


class Movimento(AziendaMixin):
    CARICO, SCARICO, RETTIFICA = "carico", "scarico", "rettifica"
    TIPI = [(CARICO, "Carico"), (SCARICO, "Scarico"), (RETTIFICA, "Rettifica")]
    data = models.DateTimeField("data", default=timezone.now)
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, related_name="movimenti",
                                 verbose_name="prodotto")
    magazzino = models.ForeignKey(Magazzino, on_delete=models.PROTECT, related_name="movimenti", verbose_name="magazzino")
    quantita = models.DecimalField("quantità", max_digits=14, decimal_places=3,
                                   help_text="positiva = entra, negativa = esce")
    tipo = models.CharField("tipo", max_length=10, choices=TIPI, default=RETTIFICA)
    causale = models.CharField("causale", max_length=200, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, editable=False)
    object_id = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    documento = GenericForeignKey("content_type", "object_id")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+", editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "movimento"
        verbose_name_plural = "movimenti"
        ordering = ["-data", "-pk"]
        indexes = [models.Index(fields=["prodotto", "magazzino"])]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.quantita} {self.prodotto}"

    def clean(self):
        if self.quantita == 0:
            raise ValidationError({"quantita": "La quantità non può essere zero."})
        if self.prodotto_id and self.prodotto.tipo != "bene":
            raise ValidationError({"prodotto": "I servizi non si movimentano a magazzino."})


def giacenza(prodotto, magazzino=None):
    qs = Movimento.objects.filter(prodotto=prodotto)
    if magazzino is not None:
        qs = qs.filter(magazzino=magazzino)
    return qs.aggregate(t=Sum("quantita"))["t"] or 0


class DocumentoMagazzino(AziendaMixin):
    """Parte comune di consegne e ricevimenti: magazzino, data, origine (ordine) e stato."""
    BOZZA, FATTO, ANNULLATO = "bozza", "fatto", "annullato"
    magazzino = models.ForeignKey(Magazzino, on_delete=models.PROTECT, verbose_name="magazzino")
    data = models.DateField("data", default=timezone.localdate)
    riferimento = models.CharField("riferimento", max_length=60, blank=True, help_text="es. numero dell'ordine")
    note = models.TextField("note", blank=True)
    origine_tipo = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
                                     related_name="+")
    origine_id = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    origine = GenericForeignKey("origine_tipo", "origine_id")

    class Meta(AziendaMixin.Meta):
        abstract = True


class Consegna(DocumentoMagazzino):
    STATI = [(DocumentoMagazzino.BOZZA, "Da spedire"), (DocumentoMagazzino.FATTO, "Spedita"),
             (DocumentoMagazzino.ANNULLATO, "Annullata")]
    CAUSALI = [("vendita", "Vendita"), ("conto_visione", "Conto visione"), ("reso", "Reso"),
               ("riparazione", "Riparazione"), ("omaggio", "Omaggio")]
    numero = models.CharField("numero DDT", max_length=30, blank=True, editable=False, db_index=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=DocumentoMagazzino.BOZZA, editable=False)
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="consegne",
                                verbose_name="destinatario")
    causale_trasporto = models.CharField("causale del trasporto", max_length=20, choices=CAUSALI, default="vendita")
    trasporto_a_cura = models.CharField("trasporto a cura del", max_length=12, default="mittente",
                                        choices=[("mittente", "Mittente"), ("destinatario", "Destinatario"),
                                                 ("vettore", "Vettore")])
    vettore = models.CharField("vettore", max_length=120, blank=True)
    colli = models.PositiveIntegerField("numero di colli", default=1)
    peso = models.DecimalField("peso (kg)", max_digits=10, decimal_places=2, null=True, blank=True)
    aspetto_beni = models.CharField("aspetto dei beni", max_length=80, blank=True, default="scatole")

    class Meta(DocumentoMagazzino.Meta):
        verbose_name = "consegna"
        verbose_name_plural = "consegne"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return self.numero or f"Consegna da spedire {self.pk}"


class RigaConsegna(models.Model):
    consegna = models.ForeignKey(Consegna, on_delete=models.CASCADE, related_name="righe", verbose_name="consegna")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]

    def save(self, *args, **kwargs):
        self.descrizione = self.descrizione or self.prodotto.nome
        super().save(*args, **kwargs)


class Ricevimento(DocumentoMagazzino):
    STATI = [(DocumentoMagazzino.BOZZA, "Da ricevere"), (DocumentoMagazzino.FATTO, "Ricevuto"),
             (DocumentoMagazzino.ANNULLATO, "Annullato")]
    stato = models.CharField("stato", max_length=10, choices=STATI, default=DocumentoMagazzino.BOZZA, editable=False)
    fornitore = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="ricevimenti",
                                  verbose_name="fornitore")
    ddt_fornitore = models.CharField("DDT del fornitore", max_length=60, blank=True)

    class Meta(DocumentoMagazzino.Meta):
        verbose_name = "ricevimento"
        verbose_name_plural = "ricevimenti"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return f"Ricevimento {self.ddt_fornitore or self.riferimento or self.pk} da {self.fornitore}"


class RigaRicevimento(models.Model):
    ricevimento = models.ForeignKey(Ricevimento, on_delete=models.CASCADE, related_name="righe",
                                    verbose_name="ricevimento")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, verbose_name="prodotto")
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]
