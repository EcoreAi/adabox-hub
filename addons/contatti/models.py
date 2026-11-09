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
                                limit_choices_to={"tipo": AZIENDA}, verbose_name="società",
                                help_text="per una persona l'azienda in cui lavora; per un'azienda la società madre")
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
    partita_iva = models.CharField("partita IVA", max_length=28, blank=True, help_text="anche estera, per il paese indicato")
    codice_fiscale = models.CharField("codice fiscale", max_length=16, blank=True,
                                      validators=[validatori.valida_codice_fiscale])
    codice_sdi = models.CharField("codice SDI", max_length=7, blank=True, validators=[validatori.valida_sdi],
                                  help_text="7 caratteri; per la Pubblica Amministrazione il codice univoco ufficio, di 6")
    pubblica_amministrazione = models.BooleanField("Pubblica Amministrazione", default=False,
                                                   help_text="fatture in formato FPA12, con il codice univoco ufficio")
    vies_valido = models.BooleanField("valida nel VIES", null=True, blank=True, editable=False)
    vies_il = models.DateTimeField("verifica VIES", null=True, blank=True, editable=False)
    cliente = models.BooleanField("cliente", default=False)
    fornitore = models.BooleanField("fornitore", default=False)
    categorie = models.ManyToManyField(Categoria, blank=True, verbose_name="categorie")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="responsabile")
    fido = models.DecimalField("fido", max_digits=14, decimal_places=2, null=True, blank=True,
                               help_text="quanto può avere aperto questo cliente, IVA compresa; vuoto = nessun controllo")
    fido_blocca = models.BooleanField("blocca oltre il fido", default=False,
                                      help_text="oltre il fido l'ordine non si conferma; altrimenti si avvisa soltanto")
    note = models.TextField("note", blank=True)
    attivo = models.BooleanField("attivo", default=True)
    classe_abc = models.CharField("classe ABC", max_length=1, blank=True, editable=False,
                                  choices=[("A", "A (primo 80% del fatturato)"), ("B", "B (fino al 95%)"), ("C", "C (il resto)")],
                                  help_text="dal fatturato degli ultimi 12 mesi, ricalcolata ogni notte")
    fatturato_12_mesi = models.DecimalField("fatturato ultimi 12 mesi", max_digits=14, decimal_places=2, default=0, editable=False)

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
        self.partita_iva = validatori.normalizza_partita_iva(self.partita_iva, self.nazione)
        if self.societa_id and self.societa_id == self.pk:
            errori["societa"] = "Un contatto non può essere la società di se stesso."
        nodo, visti = self.societa, set()
        while nodo is not None and self.pk and nodo.pk not in visti:          # niente giri: A madre di B madre di A
            if nodo.societa_id == self.pk:
                errori["societa"] = "Questa società appartiene già, direttamente o no, a questo contatto."
                break
            visti.add(nodo.pk)
            nodo = nodo.societa
        if errore := validatori.errore_partita_iva(self.partita_iva, self.nazione):
            errori["partita_iva"] = errore
        if self.pubblica_amministrazione and len(self.codice_sdi) != 6:
            errori["codice_sdi"] = "La Pubblica Amministrazione ha un codice univoco ufficio di 6 caratteri (lo trovi su IndicePA)."
        elif not self.pubblica_amministrazione and self.codice_sdi and len(self.codice_sdi) != 7:
            errori["codice_sdi"] = "Il codice destinatario ha 7 caratteri; quello di 6 è solo della Pubblica Amministrazione."
        if self.partita_iva and self.azienda_id and (
                Contatto.objects.filter(azienda_id=self.azienda_id, partita_iva=self.partita_iva)
                .exclude(pk=self.pk).exists()):
            errori["partita_iva"] = "Esiste già un contatto con questa partita IVA."
        if errori:
            raise ValidationError(errori)


class IndirizzoContatto(AziendaMixin):
    """Un indirizzo in più del contatto: consegna, fatturazione, sede operativa. Quello in anagrafica resta la sede legale."""
    CONSEGNA, FATTURAZIONE, SEDE, ALTRO = "consegna", "fatturazione", "sede", "altro"
    TIPI = [(CONSEGNA, "Consegna"), (FATTURAZIONE, "Fatturazione"), (SEDE, "Sede operativa"), (ALTRO, "Altro")]
    contatto = models.ForeignKey(Contatto, on_delete=models.CASCADE, related_name="indirizzi", verbose_name="contatto")
    tipo = models.CharField("tipo", max_length=12, choices=TIPI, default=CONSEGNA)
    nome = models.CharField("descrizione", max_length=100, blank=True, help_text="es. Magazzino di Bari")
    presso = models.CharField("presso", max_length=100, blank=True, help_text="c/o, reparto o persona")
    indirizzo = models.CharField("indirizzo", max_length=200)
    cap = models.CharField("CAP", max_length=10, blank=True)
    citta = models.CharField("città", max_length=100)
    provincia = models.CharField("provincia", max_length=2, blank=True)
    nazione = models.CharField("nazione", max_length=2, default="IT")
    predefinito = models.BooleanField("predefinito", default=False, help_text="proposto per primo per questo tipo")

    class Meta(AziendaMixin.Meta):
        verbose_name = "indirizzo"
        verbose_name_plural = "indirizzi"
        ordering = ["tipo", "-predefinito", "nome", "pk"]

    def __str__(self):
        etichetta = self.nome or self.get_tipo_display()
        return f"{etichetta}: {self.indirizzo}, {self.cap} {self.citta}".replace(" ,", ",").strip()

    @property
    def righe(self):
        """Le righe da stampare su DDT e documenti."""
        return [r for r in (self.nome, f"c/o {self.presso}" if self.presso else "", self.indirizzo,
                            " ".join(x for x in (self.cap, self.citta, f"({self.provincia})" if self.provincia else "") if x),
                            self.nazione if self.nazione != "IT" else "") if r]

    def clean(self):
        self.provincia = self.provincia.upper()
        self.nazione = (self.nazione or "IT").upper()

    def save(self, *args, **kwargs):
        if self.contatto_id and not self.azienda_id:
            self.azienda_id = self.contatto.azienda_id
        self.clean()
        super().save(*args, **kwargs)
        if self.predefinito:
            IndirizzoContatto.objects.filter(contatto=self.contatto, tipo=self.tipo, predefinito=True).exclude(pk=self.pk).update(predefinito=False)

    @classmethod
    def predefinito_per(cls, contatto, tipo):
        if contatto is None:
            return None
        return cls.objects.filter(contatto=contatto, tipo=tipo).order_by("-predefinito", "pk").first()


class Segmento(AziendaMixin):
    """Una lista di contatti con regole salvate, ricalcolata da sola: per liste, filtri, automazioni."""
    nome = models.CharField("nome", max_length=80)
    descrizione = models.TextField("descrizione", blank=True)
    solo_clienti = models.BooleanField("solo clienti", default=True)
    solo_fornitori = models.BooleanField("solo fornitori", default=False)
    tipo = models.CharField("tipo", max_length=10, choices=Contatto.TIPI, blank=True)
    categorie = models.ManyToManyField(Categoria, blank=True, related_name="+", verbose_name="con una di queste categorie")
    province = models.CharField("province", max_length=200, blank=True, help_text="sigle separate da virgola, es. MI, MB, CO")
    nazione = models.CharField("nazione", max_length=2, blank=True)
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="con responsabile")
    classi = models.CharField("classi ABC", max_length=3, blank=True, help_text="es. A oppure AB")
    fatturato_minimo = models.DecimalField("fatturato 12 mesi da (€)", max_digits=14, decimal_places=2, null=True, blank=True)
    fatturato_massimo = models.DecimalField("fatturato 12 mesi fino a (€)", max_digits=14, decimal_places=2, null=True, blank=True)
    acquisto_entro = models.PositiveIntegerField("ha comprato negli ultimi (giorni)", null=True, blank=True)
    inattivo_da = models.PositiveIntegerField("non compra da almeno (giorni)", null=True, blank=True,
                                              help_text="clienti dormienti: nessuna fattura in questo periodo")
    aggiunti = models.ManyToManyField(Contatto, blank=True, related_name="+", verbose_name="aggiunti a mano")
    esclusi = models.ManyToManyField(Contatto, blank=True, related_name="+", verbose_name="esclusi a mano")
    membri = models.ManyToManyField(Contatto, blank=True, related_name="segmenti", editable=False, verbose_name="contatti")
    numero = models.PositiveIntegerField("contatti", default=0, editable=False)
    ricalcolato_il = models.DateTimeField("ricalcolato il", null=True, blank=True, editable=False)
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "segmento"
        verbose_name_plural = "segmenti"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def clean(self):
        if self.classi and set(self.classi.upper()) - set("ABC"):
            raise ValidationError({"classi": "Solo le lettere A, B e C."})
        self.classi = "".join(sorted(set(self.classi.upper())))


# condizioni in più per le regole delle automazioni (vedi automazioni.catalogo._generici)
Contatto.condizioni_automazioni = {
    "segmenti": ("Segmenti", "testo", lambda o: ", ".join(o.segmenti.values_list("nome", flat=True))),
    "fatturato_12_mesi": ("Fatturato ultimi 12 mesi", "numero", lambda o: o.fatturato_12_mesi),
}
