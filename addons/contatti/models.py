from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.mixins import AziendaMixin, ProprietaMixin

from . import validatori


class Categoria(models.Model):
    nome = models.CharField("nome", max_length=60, unique=True)
    colore = models.CharField("colore", max_length=7, default="#1e3a8a")

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorie"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Contatto(AziendaMixin, ProprietaMixin):
    AZIENDA, PERSONA = "azienda", "persona"
    TIPI = [(AZIENDA, "Azienda"), (PERSONA, "Persona")]
    codice = models.CharField("codice", max_length=20, blank=True, editable=False, db_index=True)
    tipo = models.CharField("tipo", max_length=10, choices=TIPI, default=AZIENDA)
    nome = models.CharField("nome", max_length=200, help_text="ragione sociale, oppure nome e cognome")
    societa = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="persone",
                                limit_choices_to={"tipo": AZIENDA}, verbose_name="società")
    ruolo = models.CharField("ruolo", max_length=100, blank=True)
    email = models.EmailField("email", blank=True)
    pec = models.EmailField("PEC", blank=True)
    telefono = models.CharField("telefono", max_length=40, blank=True)
    cellulare = models.CharField("cellulare", max_length=40, blank=True)
    sito = models.URLField("sito web", blank=True)
    indirizzo = models.CharField("indirizzo", max_length=200, blank=True)
    cap = models.CharField("CAP", max_length=10, blank=True)
    citta = models.CharField("città", max_length=100, blank=True)
    provincia = models.CharField("provincia", max_length=2, blank=True)
    nazione = models.CharField("nazione", max_length=2, default="IT")
    partita_iva = models.CharField("partita IVA", max_length=11, blank=True, validators=[validatori.valida_partita_iva])
    codice_fiscale = models.CharField("codice fiscale", max_length=16, blank=True,
                                      validators=[validatori.valida_codice_fiscale])
    codice_sdi = models.CharField("codice SDI", max_length=7, blank=True, validators=[validatori.valida_sdi])
    cliente = models.BooleanField("cliente", default=False)
    fornitore = models.BooleanField("fornitore", default=False)
    categorie = models.ManyToManyField(Categoria, blank=True, verbose_name="categorie")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="responsabile")
    note = models.TextField("note", blank=True)
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "contatto"
        verbose_name_plural = "contatti"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.societa.nome})" if self.tipo == self.PERSONA and self.societa_id else self.nome

    def clean(self):
        errori = {}
        self.codice_fiscale = self.codice_fiscale.upper()
        self.codice_sdi = self.codice_sdi.upper()
        self.provincia = self.provincia.upper()
        self.nazione = (self.nazione or "IT").upper()
        if self.societa_id and self.societa_id == self.pk:
            errori["societa"] = "Un contatto non può essere la società di se stesso."
        if self.tipo == self.AZIENDA and self.societa_id:
            errori["societa"] = "Solo le persone appartengono a una società."
        if self.partita_iva and self.azienda_id and (
                Contatto.objects.filter(azienda_id=self.azienda_id, partita_iva=self.partita_iva)
                .exclude(pk=self.pk).exists()):
            errori["partita_iva"] = "Esiste già un contatto con questa partita IVA."
        if errori:
            raise ValidationError(errori)
