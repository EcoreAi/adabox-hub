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
    simbolo = models.CharField("simbolo", max_length=10, unique=True)
    nome = models.CharField("nome", max_length=40)

    class Meta:
        verbose_name = "unità di misura"
        verbose_name_plural = "unità di misura"
        ordering = ["nome"]

    def __str__(self):
        return self.simbolo


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
    unita = models.ForeignKey(UnitaMisura, on_delete=models.PROTECT, default=unita_predefinita, verbose_name="unità")
    prezzo_vendita = models.DecimalField("prezzo di vendita (€)", max_digits=12, decimal_places=4, default=0)
    costo = models.DecimalField("costo (€)", max_digits=12, decimal_places=4, default=0)
    aliquota_iva = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, default=aliquota_predefinita,
                                     verbose_name="aliquota IVA")
    codice_barre = models.CharField("codice a barre", max_length=40, blank=True)
    descrizione_vendita = models.TextField("descrizione per i documenti", blank=True)
    scorta_minima = models.DecimalField("scorta minima", max_digits=12, decimal_places=3, default=0)
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

    def clean(self):
        if self.codice and self.azienda_id and (
                Prodotto.objects.filter(azienda_id=self.azienda_id, codice=self.codice).exclude(pk=self.pk).exists()):
            raise ValidationError({"codice": "Esiste già un prodotto con questo codice."})
        if self.prezzo_vendita is not None and self.prezzo_vendita < 0:
            raise ValidationError({"prezzo_vendita": "Il prezzo non può essere negativo."})


class Listino(AziendaMixin):
    nome = models.CharField("nome", max_length=80)
    attivo = models.BooleanField("attivo", default=True)
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

    class Meta:
        verbose_name = "prezzo di listino"
        verbose_name_plural = "prezzi"
        ordering = ["prodotto", "quantita_minima"]

    def __str__(self):
        return f"{self.prodotto} da {self.quantita_minima}: {self.prezzo}"
