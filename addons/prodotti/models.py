from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from core.mixins import AziendaMixin, ProprietaMixin


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
    """Errore di form se l'unità della riga non si converte in quella del prodotto."""
    if riga.prodotto_id and riga.unita_id and not riga.unita.compatibile(riga.prodotto.unita):
        raise ValidationError({"unita": f"{riga.prodotto} si misura in {riga.prodotto.unita}: {riga.unita} non si converte."})


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
    descrizione_vendita = models.TextField("descrizione per i documenti", blank=True)
    scorta_minima = models.DecimalField("scorta minima", max_digits=12, decimal_places=3, default=0)
    kit = models.BooleanField("kit", default=False,
                              help_text="Si vende come un pezzo solo ma è fatto di altri prodotti: in consegna escono i componenti")
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "prodotto"
        verbose_name_plural = "prodotti"
        ordering = ["nome"]

    def __str__(self):
        return f"[{self.codice}] {self.nome}" if self.codice else self.nome

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
    p = prodotti.filter(codice_barre=codice).first() or prodotti.filter(codice=codice).first()
    if p is not None:
        return p, Decimal(1)
    c = Confezione.objects.filter(prodotto__in=prodotti, codice_barre=codice).select_related("prodotto").first()
    return (c.prodotto, c.quantita) if c else None
