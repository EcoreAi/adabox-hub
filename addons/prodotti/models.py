from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from core.mixins import AziendaMixin, ProprietaMixin

from . import immagini


class Categoria(models.Model):
    nome = models.CharField("nome", max_length=80, unique=True)

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorie"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class UnitaMisura(models.Model):
    """Le unità si convertono tra loro solo nella stessa categoria: il fattore dice quante unità di riferimento vale
    (peso: kg = 1, g = 0,001; pezzi: pz = 1, dozzina = 12). «Altro» non si converte."""
    PEZZI, PESO, VOLUME, LUNGHEZZA, SUPERFICIE, TEMPO, ALTRO = "pezzi", "peso", "volume", "lunghezza", "superficie", "tempo", "altro"
    CATEGORIE = [(PEZZI, "Pezzi"), (PESO, "Peso"), (VOLUME, "Volume"), (LUNGHEZZA, "Lunghezza"), (SUPERFICIE, "Superficie"),
                 (TEMPO, "Tempo"), (ALTRO, "Altro (non si converte)")]
    simbolo = models.CharField("simbolo", max_length=10, unique=True)
    nome = models.CharField("nome", max_length=40)
    categoria = models.CharField("categoria", max_length=12, choices=CATEGORIE, default=ALTRO)
    fattore = models.DecimalField("vale", max_digits=18, decimal_places=9, default=1,
                                  help_text="quante unità di riferimento della categoria (kg, pz, l, m, m², h) vale una di queste")

    class Meta:
        verbose_name = "unità di misura"
        verbose_name_plural = "unità di misura"
        ordering = ["categoria", "fattore", "nome"]

    def __str__(self):
        return self.simbolo

    def clean(self):
        if self.fattore is not None and self.fattore <= 0:
            raise ValidationError({"fattore": "Il fattore deve essere positivo."})

    def compatibile(self, altra):
        return altra is None or altra.pk == self.pk or (self.categoria == altra.categoria and self.categoria != self.ALTRO)


def converti(quantita, da, a):
    """La quantità espressa in `da` riportata in `a` (None = nessuna conversione). ValidationError fra categorie diverse."""
    if quantita is None or da is None or a is None or da.pk == a.pk:
        return quantita
    if not da.compatibile(a):
        raise ValidationError(f"Non si converte da {da} a {a}: sono di categorie diverse.")
    return (Decimal(quantita) * da.fattore / a.fattore).quantize(Decimal("0.001"))


def prepara_riga(riga, verso="vendita"):
    """Per le righe di ordini e fatture: unità predefinita del prodotto e quantità nell'unità base (quantita_base)."""
    prodotto = riga.prodotto if riga.prodotto_id else None
    if prodotto is None:
        riga.quantita_base = riga.quantita
        return
    if riga.unita_id is None:
        riga.unita = (prodotto.unita_vendita if verso == "vendita" else prodotto.unita_acquisto) or prodotto.unita
    riga.quantita_base = converti(riga.quantita, riga.unita, prodotto.unita)


def controlla_unita(riga):
    """Errore di form se il prodotto della riga è un modello con varianti o se l'unità della riga non si converte in
    quella del prodotto."""
    if riga.prodotto_id and riga.prodotto.con_varianti:
        raise ValidationError({"prodotto": f"{riga.prodotto} ha varianti: scegli la variante (taglia, colore…)."})
    if riga.prodotto_id and riga.unita_id and not riga.unita.compatibile(riga.prodotto.unita):
        raise ValidationError({"unita": f"{riga.prodotto} si misura in {riga.prodotto.unita}: {riga.unita} non si converte."})


class Attributo(models.Model):
    """Ciò per cui le varianti di un prodotto si distinguono: taglia, colore, materiale."""
    nome = models.CharField("nome", max_length=60, unique=True)
    ordine = models.PositiveSmallIntegerField("ordine", default=0)

    class Meta:
        verbose_name = "attributo"
        verbose_name_plural = "attributi"
        ordering = ["ordine", "nome"]

    def __str__(self):
        return self.nome


class ValoreAttributo(models.Model):
    attributo = models.ForeignKey(Attributo, on_delete=models.CASCADE, related_name="valori", verbose_name="attributo")
    nome = models.CharField("valore", max_length=60)
    codice = models.CharField("sigla", max_length=12, blank=True, help_text="entra nel codice della variante (es. RO per Rosso); vuoto = il valore")
    sovrapprezzo = models.DecimalField("sovrapprezzo (€)", max_digits=12, decimal_places=4, default=0,
                                       help_text="si somma al prezzo del modello nelle varianti generate")
    ordine = models.PositiveSmallIntegerField("ordine", default=0)

    class Meta:
        verbose_name = "valore dell'attributo"
        verbose_name_plural = "valori"
        ordering = ["attributo__ordine", "attributo__nome", "ordine", "pk"]
        constraints = [models.UniqueConstraint(fields=["attributo", "nome"], name="prodotti_valore_unico")]

    def __str__(self):
        return f"{self.attributo}: {self.nome}"

    @property
    def sigla(self):
        return (self.codice or self.nome).strip().upper().replace(" ", "")[:12]


def aliquota_predefinita():
    from fiscale.models import AliquotaIva
    return AliquotaIva.objects.filter(codice="22").values_list("pk", flat=True).first()


def unita_predefinita():
    return UnitaMisura.objects.filter(simbolo="pz").values_list("pk", flat=True).first()


class Prodotto(AziendaMixin, ProprietaMixin):
    BENE, SERVIZIO = "bene", "servizio"
    codice = models.CharField("codice", max_length=40, blank=True, db_index=True,
                              help_text="vuoto = assegnato in automatico")
    nome = models.CharField("nome", max_length=200)
    tipo = models.CharField("tipo", max_length=8, choices=[(BENE, "Bene"), (SERVIZIO, "Servizio")], default=BENE)
    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="categoria")
    unita = models.ForeignKey(UnitaMisura, on_delete=models.PROTECT, default=unita_predefinita, verbose_name="unità",
                              help_text="l'unità del magazzino: giacenze e movimenti sono in questa")
    unita_vendita = models.ForeignKey(UnitaMisura, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                      verbose_name="unità di vendita", help_text="vuoto = come l'unità del prodotto")
    unita_acquisto = models.ForeignKey(UnitaMisura, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                       verbose_name="unità di acquisto", help_text="vuoto = come l'unità del prodotto")
    prezzo_vendita = models.DecimalField("prezzo di vendita (€)", max_digits=12, decimal_places=4, default=0)
    costo = models.DecimalField("costo (€)", max_digits=12, decimal_places=4, default=0)
    aliquota_iva = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, default=aliquota_predefinita,
                                     verbose_name="aliquota IVA")
    codice_barre = models.CharField("codice a barre", max_length=40, blank=True)
    peso = models.DecimalField("peso unitario (kg)", max_digits=10, decimal_places=3, null=True, blank=True)
    descrizione_vendita = models.TextField("descrizione per i documenti", blank=True)
    scorta_minima = models.DecimalField("scorta minima", max_digits=12, decimal_places=3, default=0)
    kit = models.BooleanField("kit", default=False,
                              help_text="Si vende come un pezzo solo ma è fatto di altri prodotti: in consegna escono i componenti")
    attivo = models.BooleanField("attivo", default=True)
    immagine = models.ImageField("immagine", upload_to=immagini.percorso, storage=immagini.storage, max_length=300,
                                 blank=True, validators=[immagini.valida],
                                 help_text="JPEG, PNG, WebP o GIF: si riduce da sola e perde i dati della fotocamera")
    con_varianti = models.BooleanField("con varianti", default=False,
                                       help_text="È il modello di più varianti (taglie, colori…): si vendono e si tengono a "
                                                 "magazzino le varianti, non il modello")
    variante_di = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="varianti",
                                    limit_choices_to={"con_varianti": True}, verbose_name="variante di")
    valori = models.ManyToManyField(ValoreAttributo, blank=True, related_name="varianti", verbose_name="valori",
                                    help_text="per una variante: i valori che la distinguono")
    alternativi = models.ManyToManyField("self", blank=True, verbose_name="prodotti alternativi",
                                         help_text="si possono proporre al posto di questo (vale nei due sensi)")

    class Meta(AziendaMixin.Meta):
        verbose_name = "prodotto"
        verbose_name_plural = "prodotti"
        ordering = ["nome"]

    def __str__(self):
        return f"[{self.codice}] {self.nome}" if self.codice else self.nome

    CAMPI_COMUNI = ("categoria", "aliquota_iva", "unita_vendita", "unita_acquisto")    # dal modello alle varianti

    def save(self, *args, **kwargs):
        vecchio = immagini.prepara(self, "immagine")
        super().save(*args, **kwargs)
        if vecchio:
            transaction.on_commit(lambda: immagini.storage.delete(vecchio))
        if self.con_varianti:
            comuni = {f"{c}_id": getattr(self, f"{c}_id") for c in self.CAMPI_COMUNI}
            if not self.attivo:
                comuni["attivo"] = False
            self.varianti.update(**comuni)

    @property
    def url_immagine(self):
        """L'URL dell'immagine da mostrare (anche quella della galleria o del modello), '' se non c'è."""
        return immagini.url(self)

    @property
    def a_magazzino(self):
        return self.tipo == self.BENE

    def esploso(self, quantita=1):
        """[(componente, quantità)] per `quantita` pezzi: i componenti se è un kit con componenti, altrimenti sé stesso."""
        if not self.kit:
            return [(self, Decimal(quantita))]
        componenti = [(c.componente, c.quantita * Decimal(quantita)) for c in self.componenti.select_related("componente")]
        return componenti or [(self, Decimal(quantita))]

    def clean(self):
        for campo in ("unita_vendita", "unita_acquisto"):
            altra = getattr(self, campo)
            if altra is not None and self.unita_id and not altra.compatibile(self.unita):
                raise ValidationError({campo: f"Non si converte in {self.unita}: scegli un'unità della stessa categoria."})
        if self.codice and self.azienda_id and (
                Prodotto.objects.filter(azienda_id=self.azienda_id, codice=self.codice).exclude(pk=self.pk).exists()):
            raise ValidationError({"codice": "Esiste già un prodotto con questo codice."})
        if self.prezzo_vendita is not None and self.prezzo_vendita < 0:
            raise ValidationError({"prezzo_vendita": "Il prezzo non può essere negativo."})
        if self.variante_di_id:
            if self.con_varianti:
                raise ValidationError({"variante_di": "Un modello con varianti non è a sua volta una variante."})
            if self.variante_di_id == self.pk or not self.variante_di.con_varianti:
                raise ValidationError({"variante_di": "Scegli un prodotto segnato «con varianti»."})
            if self.variante_di.azienda_id != self.azienda_id:
                raise ValidationError({"variante_di": "Il modello è di un'altra azienda."})
        if self.con_varianti and self.kit:
            raise ValidationError({"kit": "Un modello con varianti non è un kit: lo possono essere le sue varianti."})
        if self.codice_barre and self.azienda_id:
            uguale = codice_in_uso(self.azienda_id, self.codice_barre, escluso=self)
            if uguale:
                raise ValidationError({"codice_barre": f"Il codice a barre è già di {uguale}."})

    @property
    def nome_variante(self):
        """«Rosso, M»: i valori della variante nell'ordine degli attributi ('' se non è una variante)."""
        return ", ".join(v.nome for v in sorted(self.valori.all(), key=lambda v: (v.attributo.ordine, v.attributo.nome, v.ordine)))


class ImmagineProdotto(models.Model):
    """Le altre foto del prodotto, oltre a quella principale: lati, dettagli, ambientate."""
    prodotto = models.ForeignKey(Prodotto, on_delete=models.CASCADE, related_name="immagini", verbose_name="prodotto")
    file = models.ImageField("immagine", upload_to=immagini.percorso, storage=immagini.storage, max_length=300,
                             validators=[immagini.valida])
    didascalia = models.CharField("didascalia", max_length=200, blank=True)
    ordine = models.PositiveSmallIntegerField("ordine", default=0)

    class Meta:
        verbose_name = "immagine del prodotto"
        verbose_name_plural = "immagini del prodotto"
        ordering = ["ordine", "pk"]

    def __str__(self):
        return self.didascalia or f"Immagine di {self.prodotto}"

    def save(self, *args, **kwargs):
        vecchio = immagini.prepara(self, "file")
        super().save(*args, **kwargs)
        if vecchio:
            transaction.on_commit(lambda: immagini.storage.delete(vecchio))


@receiver(post_delete, sender=Prodotto)
@receiver(post_delete, sender=ImmagineProdotto)
def _cancella_file(sender, instance, **kwargs):
    """Il file se ne va con il record (dopo il commit, se la cancellazione viene annullata resta)."""
    nome = (instance.immagine if sender is Prodotto else instance.file).name
    if nome:
        transaction.on_commit(lambda: immagini.storage.delete(nome))


class AttributoProdotto(models.Model):
    """Su un modello con varianti: un attributo e i valori in cui esiste (es. Taglia: S, M, L)."""
    prodotto = models.ForeignKey(Prodotto, on_delete=models.CASCADE, related_name="attributi", verbose_name="prodotto")
    attributo = models.ForeignKey(Attributo, on_delete=models.PROTECT, related_name="+", verbose_name="attributo")
    valori = models.ManyToManyField(ValoreAttributo, related_name="+", verbose_name="valori")

    class Meta:
        verbose_name = "attributo del prodotto"
        verbose_name_plural = "attributi delle varianti"
        ordering = ["attributo__ordine", "attributo__nome"]
        constraints = [models.UniqueConstraint(fields=["prodotto", "attributo"], name="prodotti_attributo_unico")]

    def __str__(self):
        return f"{self.attributo} di {self.prodotto}"


class CodiceBarre(models.Model):
    """Altri codici a barre dello stesso articolo (EAN del produttore, vecchi codici, codici del distributore)."""
    prodotto = models.ForeignKey(Prodotto, on_delete=models.CASCADE, related_name="codici_barre", verbose_name="prodotto")
    codice = models.CharField("codice a barre", max_length=40)
    nota = models.CharField("nota", max_length=80, blank=True, help_text="es. EAN del produttore")

    class Meta:
        verbose_name = "codice a barre"
        verbose_name_plural = "altri codici a barre"
        ordering = ["pk"]

    def __str__(self):
        return self.codice

    def clean(self):
        self.codice = (self.codice or "").strip()
        if self.codice and self.prodotto_id:
            uguale = codice_in_uso(self.prodotto.azienda_id, self.codice, escluso=self.prodotto)
            if uguale:
                raise ValidationError({"codice": f"Il codice a barre è già di {uguale}."})


class CodiceCliente(models.Model):
    """Come un cliente chiama l'articolo: il suo codice esce sui documenti che riceve e nella fattura elettronica."""
    prodotto = models.ForeignKey(Prodotto, on_delete=models.CASCADE, related_name="codici_cliente", verbose_name="prodotto")
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.CASCADE, related_name="codici_prodotto",
                                verbose_name="cliente")
    codice = models.CharField("codice del cliente", max_length=35)
    descrizione = models.CharField("descrizione del cliente", max_length=200, blank=True)

    class Meta:
        verbose_name = "codice cliente"
        verbose_name_plural = "codici dei clienti"
        ordering = ["cliente__nome", "pk"]
        constraints = [models.UniqueConstraint(fields=["prodotto", "cliente"], name="prodotti_codice_cliente_unico")]

    def __str__(self):
        return f"{self.codice} ({self.cliente})"


def codice_cliente(prodotto, cliente):
    """Il CodiceCliente di quel cliente per il prodotto, o None."""
    if prodotto is None or cliente is None:
        return None
    return CodiceCliente.objects.filter(prodotto=prodotto, cliente=cliente).first()


def codice_in_uso(azienda_id, codice, escluso=None):
    """Il prodotto dell'azienda (diverso da `escluso`) che usa già quel codice a barre, principale o aggiuntivo."""
    altri = Prodotto.objects.filter(azienda_id=azienda_id)
    if escluso is not None and escluso.pk:
        altri = altri.exclude(pk=escluso.pk)
    return altri.filter(models.Q(codice_barre=codice) | models.Q(codici_barre__codice=codice)).first()


class Listino(AziendaMixin):
    nome = models.CharField("nome", max_length=80)
    attivo = models.BooleanField("attivo", default=True)
    iva_inclusa = models.BooleanField("prezzi IVA inclusa", default=False,
                                      help_text="es. un listino al pubblico: sui documenti il prezzo si scorpora con l'aliquota della riga")
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "listino"
        verbose_name_plural = "listini"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class PrezzoListino(models.Model):
    listino = models.ForeignKey(Listino, on_delete=models.CASCADE, related_name="prezzi", verbose_name="listino")
    prodotto = models.ForeignKey(Prodotto, on_delete=models.CASCADE, related_name="prezzi_listino",
                                 verbose_name="prodotto")
    quantita_minima = models.DecimalField("da quantità", max_digits=12, decimal_places=3, default=1)
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4)
    valido_dal = models.DateField("valido dal", null=True, blank=True)
    valido_al = models.DateField("valido al", null=True, blank=True)

    class Meta:
        verbose_name = "prezzo di listino"
        verbose_name_plural = "prezzi"
        ordering = ["prodotto", "quantita_minima"]

    def __str__(self):
        return f"{self.prodotto} da {self.quantita_minima}: {self.prezzo}"


class Confezione(models.Model):
    """Come arriva o si spedisce il prodotto: scatola da 12, pallet da 480. Il codice a barre della confezione vale
    tutti i suoi pezzi; le confezioni danno i colli suggeriti sul DDT."""
    prodotto = models.ForeignKey(Prodotto, on_delete=models.CASCADE, related_name="confezioni", verbose_name="prodotto")
    nome = models.CharField("confezione", max_length=60, help_text="es. Scatola, Cartone, Pallet")
    quantita = models.DecimalField("pezzi", max_digits=12, decimal_places=3, default=1)
    codice_barre = models.CharField("codice a barre", max_length=40, blank=True)
    peso = models.DecimalField("peso (kg)", max_digits=10, decimal_places=3, null=True, blank=True)

    class Meta:
        verbose_name = "confezione"
        verbose_name_plural = "confezioni"
        ordering = ["quantita", "pk"]

    def __str__(self):
        return f"{self.nome} da {self.quantita.normalize():f}"

    def clean(self):
        if self.quantita is not None and self.quantita <= 0:
            raise ValidationError({"quantita": "Una confezione contiene almeno un pezzo."})


class ComponenteKit(models.Model):
    """Un pezzo del kit: quanti ne servono per farne uno."""
    kit = models.ForeignKey(Prodotto, on_delete=models.CASCADE, related_name="componenti", verbose_name="kit")
    componente = models.ForeignKey(Prodotto, on_delete=models.PROTECT, related_name="nei_kit", verbose_name="componente")
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)

    class Meta:
        verbose_name = "componente del kit"
        verbose_name_plural = "componenti del kit"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.quantita.normalize():f} × {self.componente}"

    def clean(self):
        if self.quantita is not None and self.quantita <= 0:
            raise ValidationError({"quantita": "Scrivi quanti pezzi servono."})
        if self.componente_id and self.kit_id:
            if self.componente_id == self.kit_id:
                raise ValidationError({"componente": "Un kit non contiene sé stesso."})
            if self.componente.kit:
                raise ValidationError({"componente": "Un componente non può essere a sua volta un kit."})
            if self.componente.tipo != Prodotto.BENE:
                raise ValidationError({"componente": "I componenti sono beni di magazzino."})


def da_codice(azienda, codice):
    """(prodotto, pezzi) dal codice a barre di un prodotto o di una sua confezione (o dal codice del prodotto), o None."""
    codice = (codice or "").strip()
    if not codice:
        return None
    prodotti = Prodotto.objects.filter(azienda=azienda, attivo=True)
    p = (prodotti.filter(codice_barre=codice).first() or prodotti.filter(codici_barre__codice=codice).first()
         or prodotti.filter(codice=codice).first())
    if p is not None:
        return p, Decimal(1)
    c = Confezione.objects.filter(prodotto__in=prodotti, codice_barre=codice).select_related("prodotto").first()
    return (c.prodotto, c.quantita) if c else None
