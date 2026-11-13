from django.core.exceptions import ValidationError
from django.db import models, transaction

LOGO_TIPI = {"image/svg+xml", "image/png", "image/jpeg", "image/webp"}


class Tema(models.Model):
    """Un aspetto grafico dell'applicazione, scelto dall'admin di Django.

    Il tema si appoggia sempre al foglio di base (theme/ui.css, i token di theme/tokens.css): aggiunge un foglio
    che ridefinisce i token e quello che serve. Uno solo è attivo; senza temi attivi resta l'aspetto di base.
    I temi «di sistema» (Adabox Classico, Adabox Green) arrivano con l'applicazione e prendono il foglio dagli
    statici; quelli caricati dall'admin tengono il CSS (e il logo, se c'è) nel database: niente file da pubblicare."""

    nome = models.CharField(max_length=80, unique=True)
    descrizione = models.CharField(max_length=255, blank=True)
    attivo = models.BooleanField(default=False, help_text="Il tema usato da tutti. Attivarne uno spegne gli altri.")
    di_sistema = models.BooleanField(default=False, editable=False)
    foglio = models.CharField("foglio statico", max_length=200, blank=True, editable=False,
                              help_text="Percorso tra gli statici dell'applicazione (solo i temi di sistema).")
    css = models.TextField("CSS", blank=True,
                           help_text="Caricato da file o scritto qui; viene dopo il foglio di base. Per partire da un "
                                     "tema esistente usa l'azione «Duplica» nell'elenco.")
    colore_barra = models.CharField("colore della barra del browser", max_length=7, blank=True,
                                    help_text="Esadecimale, es. #22394a: barra del telefono e app installata.")
    logo = models.BinaryField(blank=True, null=True, editable=False)
    logo_tipo = models.CharField(max_length=40, blank=True, editable=False)
    aggiornato = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "tema"
        verbose_name_plural = "temi"
        ordering = ["-di_sistema", "nome"]
        constraints = [models.UniqueConstraint(fields=["attivo"], condition=models.Q(attivo=True), name="un_solo_tema_attivo")]

    def __str__(self):
        return self.nome

    def clean(self):
        c = self.colore_barra
        if c and not (len(c) == 7 and c[0] == "#" and all(x in "0123456789abcdefABCDEF" for x in c[1:])):
            raise ValidationError({"colore_barra": "Scrivi il colore come #rrggbb."})
        if "</style" in (self.css or "").lower():
            raise ValidationError({"css": "Il CSS non può contenere «</style»."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.attivo:
                Tema.objects.filter(attivo=True).exclude(pk=self.pk).update(attivo=False)
            super().save(*args, **kwargs)

    def attiva(self):
        self.attivo = True
        self.save()
