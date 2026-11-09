"""Le casse dell'azienda: contanti in sede, piccola cassa, cassa di un negozio. Niente IBAN e niente contabilità: entrate
e uscite, e ogni tanto la chiusura che confronta il saldo atteso con i soldi contati."""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.mixins import AziendaMixin


class Cassa(AziendaMixin):
    nome = models.CharField("nome", max_length=80, help_text="es. Cassa sede, Piccola cassa ufficio")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                     verbose_name="responsabile")
    saldo_iniziale = models.DecimalField("saldo iniziale", max_digits=14, decimal_places=2, default=Decimal(0),
                                         help_text="I contanti presenti il giorno in cui si comincia a usarla")
    dal = models.DateField("in uso dal", default=timezone.localdate)
    predefinita = models.BooleanField("predefinita", default=False,
                                      help_text="Gli incassi delle fatture in contanti entrano qui da soli")
    attiva = models.BooleanField("attiva", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "cassa"
        verbose_name_plural = "casse"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def saldo_al(self, data=None):
        """I contanti attesi a fine giornata `data` (oggi se manca)."""
        qs = self.movimenti.all() if data is None else self.movimenti.filter(data__lte=data)
        return self.saldo_iniziale + (qs.aggregate(t=Sum("importo"))["t"] or Decimal(0))

    @property
    def saldo(self):
        return self.saldo_al()

    def ultima_chiusura(self):
        return self.chiusure.order_by("-data", "-pk").first()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.predefinita:                            # una sola predefinita per azienda
            Cassa.objects.filter(azienda_id=self.azienda_id, predefinita=True).exclude(pk=self.pk).update(predefinita=False)


class ChiusuraCassa(AziendaMixin):
    """La quadratura a fine giornata (o settimana): saldo atteso, contanti contati, differenza registrata come movimento."""
    cassa = models.ForeignKey(Cassa, on_delete=models.CASCADE, related_name="chiusure", verbose_name="cassa")
    data = models.DateField("data")
    apertura = models.DecimalField("saldo di apertura", max_digits=14, decimal_places=2, help_text="il contato della chiusura precedente")
    entrate = models.DecimalField("entrate", max_digits=14, decimal_places=2, default=Decimal(0))
    uscite = models.DecimalField("uscite", max_digits=14, decimal_places=2, default=Decimal(0))
    atteso = models.DecimalField("saldo atteso", max_digits=14, decimal_places=2)
    contato = models.DecimalField("contanti contati", max_digits=14, decimal_places=2)
    differenza = models.DecimalField("differenza", max_digits=14, decimal_places=2, default=Decimal(0),
                                     help_text="positiva se in cassa c'è più dell'atteso")
    nota = models.CharField("nota", max_length=300, blank=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name="chiusa da")
    creata = models.DateTimeField("registrata il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "chiusura di cassa"
        verbose_name_plural = "chiusure di cassa"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return f"{self.cassa} al {self.data:%d/%m/%Y}"


class MovimentoCassa(AziendaMixin):
    """Contanti che entrano (importo positivo) o escono (negativo). Dopo una chiusura non si cambiano più."""
    INCASSO, RIMBORSO, SPESA, VERSAMENTO, PRELIEVO, DIFFERENZA, ALTRO = (
        "incasso", "rimborso", "spesa", "versamento", "prelievo", "differenza", "altro")
    CAUSALI = [(INCASSO, "Incasso"), (RIMBORSO, "Rimborso spese"), (SPESA, "Spesa pagata in contanti"),
               (VERSAMENTO, "Versamento in banca"), (PRELIEVO, "Prelievo dalla banca"), (DIFFERENZA, "Differenza di cassa"),
               (ALTRO, "Altro")]
    USCITE = {RIMBORSO, SPESA, VERSAMENTO}
    cassa = models.ForeignKey(Cassa, on_delete=models.CASCADE, related_name="movimenti", verbose_name="cassa")
    data = models.DateField("data", default=timezone.localdate)
    causale = models.CharField("causale", max_length=12, choices=CAUSALI, default=ALTRO)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, help_text="positivo se entra, negativo se esce")
    descrizione = models.CharField("descrizione", max_length=200, blank=True)
    controparte = models.CharField("da o per chi", max_length=120, blank=True)
    incasso = models.OneToOneField("fatturazione.Incasso", on_delete=models.SET_NULL, null=True, blank=True, related_name="in_cassa",
                                   verbose_name="incasso della fattura", editable=False)
    tipo_documento = models.ForeignKey("contenttypes.ContentType", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                       editable=False)
    id_documento = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    chiusura = models.ForeignKey(ChiusuraCassa, on_delete=models.SET_NULL, null=True, blank=True, related_name="movimenti",
                                 verbose_name="chiusura", editable=False)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name="registrato da", editable=False)
    creato = models.DateTimeField("registrato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "movimento di cassa"
        verbose_name_plural = "movimenti di cassa"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return f"{self.get_causale_display()} {self.importo} € del {self.data:%d/%m/%Y}"

    @property
    def documento(self):
        if self.tipo_documento_id and self.id_documento:
            return self.tipo_documento.model_class()._default_manager.filter(pk=self.id_documento).first()
        return None

    def clean(self):
        if self.importo == 0:
            raise ValidationError({"importo": "Scrivi un importo diverso da zero."})
        if self.causale in self.USCITE and self.importo and self.importo > 0:
            self.importo = -self.importo                     # rimborsi, spese e versamenti escono sempre
        if self.causale == self.PRELIEVO and self.importo and self.importo < 0:
            self.importo = -self.importo
        if self.cassa_id:
            chiusa = self.cassa.ultima_chiusura()
            if chiusa and self.data and self.data <= chiusa.data:
                raise ValidationError({"data": f"La cassa è chiusa fino al {chiusa.data:%d/%m/%Y}: usa una data successiva."})
            if self.data and self.data < self.cassa.dal:
                raise ValidationError({"data": f"La cassa è in uso dal {self.cassa.dal:%d/%m/%Y}."})
