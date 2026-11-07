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


class Ubicazione(AziendaMixin):
    """Zona, scaffale o cella di un magazzino, ad albero (es. A → A-01 → A-01-3)."""
    magazzino = models.ForeignKey(Magazzino, on_delete=models.CASCADE, related_name="ubicazioni", verbose_name="magazzino")
    padre = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="figlie",
                              verbose_name="dentro a")
    codice = models.CharField("codice", max_length=30, help_text="es. A-01-3")
    nome = models.CharField("descrizione", max_length=80, blank=True, help_text="es. Scaffale 1, ripiano 3")
    predefinita = models.BooleanField("predefinita", default=False,
                                      help_text="dove vanno i carichi e da dove partono le uscite senza ubicazione")
    attiva = models.BooleanField("attiva", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "ubicazione"
        verbose_name_plural = "ubicazioni"
        ordering = ["magazzino__nome", "codice"]
        constraints = [models.UniqueConstraint(fields=["magazzino", "codice"], name="magazzino_ubicazione_unica")]

    def __str__(self):
        return f"{self.magazzino} · {self.codice}"

    @property
    def percorso(self):
        nodi, nodo, visti = [], self, set()
        while nodo is not None and nodo.pk not in visti:
            visti.add(nodo.pk)
            nodi.append(nodo.codice)
            nodo = nodo.padre
        return " / ".join(reversed(nodi))

    def clean(self):
        if self.padre_id:
            if self.padre.magazzino_id != self.magazzino_id:
                raise ValidationError({"padre": "L'ubicazione che la contiene deve essere nello stesso magazzino."})
            nodo, visti = self.padre, set()
            while nodo is not None:
                if nodo.pk == self.pk or nodo.pk in visti:
                    raise ValidationError({"padre": "Un'ubicazione non può stare dentro sé stessa."})
                visti.add(nodo.pk)
                nodo = nodo.padre
        if self.magazzino_id and self.azienda_id and self.magazzino.azienda_id != self.azienda_id:
            raise ValidationError({"magazzino": "Magazzino di un'altra azienda."})

    def save(self, *args, **kwargs):
        if self.magazzino_id and not self.azienda_id:
            self.azienda_id = self.magazzino.azienda_id
        super().save(*args, **kwargs)
        if self.predefinita:
            Ubicazione.objects.filter(magazzino=self.magazzino, predefinita=True).exclude(pk=self.pk).update(predefinita=False)

    @classmethod
    def predefinita_di(cls, magazzino):
        return cls.objects.filter(magazzino=magazzino, predefinita=True, attiva=True).first()


class Tracciamento(models.Model):
    """Se il bene si segue per lotto o per numero di serie (di base no)."""
    NESSUNO, LOTTO, SERIALE = "", "lotto", "seriale"
    prodotto = models.OneToOneField("prodotti.Prodotto", on_delete=models.CASCADE, related_name="tracciamento",
                                    verbose_name="prodotto")
    tipo = models.CharField("tracciamento", max_length=10, blank=True,
                            choices=[(NESSUNO, "Nessuno"), (LOTTO, "Per lotto"), (SERIALE, "Per numero di serie")])
    scadenza = models.BooleanField("con data di scadenza", default=False)

    class Meta:
        verbose_name = "tracciamento"
        verbose_name_plural = "tracciamenti"

    def __str__(self):
        return f"{self.prodotto}: {self.get_tipo_display()}"


def tracciamento(prodotto):
    t = getattr(prodotto, "tracciamento", None)
    return t.tipo if t is not None else ""


class Lotto(AziendaMixin):
    """Un lotto o un numero di serie di un bene. Il seriale è un lotto da una unità."""
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, related_name="lotti", verbose_name="prodotto")
    codice = models.CharField("codice", max_length=60)
    seriale = models.BooleanField("numero di serie", default=False, editable=False)
    scadenza = models.DateField("scadenza", null=True, blank=True)
    note = models.TextField("note", blank=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "lotto o seriale"
        verbose_name_plural = "lotti e seriali"
        ordering = ["prodotto__nome", "scadenza", "codice"]
        constraints = [models.UniqueConstraint(fields=["prodotto", "codice"], name="magazzino_lotto_unico")]

    def __str__(self):
        return f"{self.codice} · {self.prodotto}"

    def save(self, *args, **kwargs):
        if self.prodotto_id and not self.azienda_id:
            self.azienda_id = self.prodotto.azienda_id
        if self._state.adding:
            self.seriale = tracciamento(self.prodotto) == Tracciamento.SERIALE
        super().save(*args, **kwargs)


class Movimento(AziendaMixin):
    CARICO, SCARICO, RETTIFICA, TRASFERIMENTO = "carico", "scarico", "rettifica", "trasferimento"
    TIPI = [(CARICO, "Carico"), (SCARICO, "Scarico"), (RETTIFICA, "Rettifica"), (TRASFERIMENTO, "Trasferimento")]
    data = models.DateTimeField("data", default=timezone.now)
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, related_name="movimenti",
                                 verbose_name="prodotto")
    magazzino = models.ForeignKey(Magazzino, on_delete=models.PROTECT, related_name="movimenti", verbose_name="magazzino")
    ubicazione = models.ForeignKey(Ubicazione, on_delete=models.PROTECT, null=True, blank=True, related_name="movimenti",
                                   verbose_name="ubicazione")
    lotto = models.ForeignKey(Lotto, on_delete=models.PROTECT, null=True, blank=True, related_name="movimenti",
                              verbose_name="lotto o seriale")
    quantita = models.DecimalField("quantità", max_digits=14, decimal_places=3,
                                   help_text="positiva = entra, negativa = esce")
    tipo = models.CharField("tipo", max_length=14, choices=TIPI, default=RETTIFICA)
    causale = models.CharField("causale", max_length=200, blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, editable=False)
    object_id = models.PositiveBigIntegerField(null=True, blank=True, editable=False)
    documento = GenericForeignKey("content_type", "object_id")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+", editable=False)
    costo_unitario = models.DecimalField("costo unitario (€)", max_digits=14, decimal_places=4, null=True, blank=True,
                                         help_text="per un carico a mano; vuoto = il costo attuale del prodotto")
    valore = models.DecimalField("valore (€)", max_digits=14, decimal_places=2, null=True, blank=True, editable=False)
    costo_fissato = models.BooleanField("costo dato all'entrata", default=False, editable=False,
                                        help_text="il costo viene dall'acquisto o da chi ha fatto il carico: il ricalcolo non lo cambia")

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
        if self.ubicazione_id and self.magazzino_id and self.ubicazione.magazzino_id != self.magazzino_id:
            raise ValidationError({"ubicazione": "L'ubicazione è di un altro magazzino."})
        if self.lotto_id and self.prodotto_id and self.lotto.prodotto_id != self.prodotto_id:
            raise ValidationError({"lotto": "Il lotto è di un altro prodotto."})
        if self.prodotto_id and tracciamento(self.prodotto) and not self.lotto_id:
            raise ValidationError({"lotto": "Questo prodotto si segue per lotto o seriale: indicalo."})
        if self.lotto_id and self.lotto.seriale and self.quantita is not None and abs(self.quantita) != 1:
            raise ValidationError({"quantita": "Un numero di serie si muove una unità alla volta."})
        if self.costo_unitario is not None and self.costo_unitario < 0:
            raise ValidationError({"costo_unitario": "Il costo non può essere negativo."})
        if self.costo_unitario is not None and self.quantita is not None and self.quantita < 0:
            raise ValidationError({"costo_unitario": "Il costo si indica solo per i carichi: le uscite prendono il costo di magazzino."})

    def save(self, *args, **kwargs):
        if self._state.adding and self.ubicazione_id is None and self.magazzino_id:
            self.ubicazione = (Ubicazione.predefinita_di(self.magazzino) if self.quantita > 0
                               else ubicazione_di_prelievo(self.prodotto, self.magazzino, self.lotto))
        if self._state.adding and self.costo_unitario is not None and self.quantita > 0:
            self.costo_fissato = True                  # costo dell'acquisto o di chi carica: il ricalcolo lo tiene
        super().save(*args, **kwargs)


def ubicazione_di_prelievo(prodotto, magazzino, lotto=None):
    """Da dove esce la merce se nessuno lo dice: l'ubicazione che ne ha di più, altrimenti la predefinita."""
    filtro = {"lotto": lotto} if lotto is not None else {}
    saldi = (Movimento.objects.filter(prodotto=prodotto, magazzino=magazzino, ubicazione__isnull=False, **filtro)
             .values("ubicazione").annotate(t=Sum("quantita")).filter(t__gt=0).order_by("-t"))
    primo = saldi.first()
    return Ubicazione.objects.get(pk=primo["ubicazione"]) if primo else Ubicazione.predefinita_di(magazzino)


def giacenza(prodotto, magazzino=None, ubicazione=None, lotto=None):
    qs = Movimento.objects.filter(prodotto=prodotto)
    if lotto is not None:
        qs = qs.filter(lotto=lotto)
    if magazzino is not None:
        qs = qs.filter(magazzino=magazzino)
    if ubicazione is not None:
        qs = qs.filter(ubicazione=ubicazione)
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
    destinazione = models.ForeignKey("contatti.IndirizzoContatto", on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="luogo di destinazione",
                                     help_text="vuoto = la sede del destinatario")
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

    def clean(self):
        if self.destinazione_id and self.cliente_id and self.destinazione.contatto_id != self.cliente_id:
            raise ValidationError({"destinazione": "L'indirizzo è di un altro contatto."})


class RigaConsegna(models.Model):
    consegna = models.ForeignKey(Consegna, on_delete=models.CASCADE, related_name="righe", verbose_name="consegna")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    ubicazione = models.ForeignKey(Ubicazione, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                   verbose_name="preleva da", help_text="vuoto = dove ce n'è di più")
    lotti = models.TextField("lotti o seriali", blank=True,
                             help_text="es. L24A:5, L24B:3 oppure un seriale per riga; vuoto = i lotti che scadono prima")

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]

    def clean(self):
        if self.ubicazione_id and self.consegna_id and self.ubicazione.magazzino_id != self.consegna.magazzino_id:
            raise ValidationError({"ubicazione": "L'ubicazione è di un altro magazzino."})

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
    costo = models.DecimalField("costo unitario (€)", max_digits=14, decimal_places=4, null=True, blank=True,
                                help_text="vuoto = prezzo dell'ordine d'acquisto, al netto dello sconto")
    ubicazione = models.ForeignKey(Ubicazione, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                   verbose_name="metti in", help_text="vuoto = l'ubicazione predefinita del magazzino")
    lotti = models.TextField("lotti o seriali", blank=True, help_text="es. L24A:5, L24B:3 oppure un seriale per riga")

    def clean(self):
        if self.ubicazione_id and self.ricevimento_id and self.ubicazione.magazzino_id != self.ricevimento.magazzino_id:
            raise ValidationError({"ubicazione": "L'ubicazione è di un altro magazzino."})

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]


class MetodoCosto(models.Model):
    """Il metodo di costo di un prodotto, se diverso da quello dell'azienda."""
    prodotto = models.OneToOneField("prodotti.Prodotto", on_delete=models.CASCADE, related_name="metodo_costo",
                                    verbose_name="prodotto")
    metodo = models.CharField("metodo di costo", max_length=10, blank=True,
                              choices=[("", "Come l'azienda"), ("medio", "Costo medio ponderato"),
                                       ("fifo", "FIFO (primo entrato, primo uscito)"), ("standard", "Costo standard del prodotto")])

    class Meta:
        verbose_name = "metodo di costo"
        verbose_name_plural = "metodi di costo"

    def __str__(self):
        return f"{self.prodotto}: {self.get_metodo_display()}"
