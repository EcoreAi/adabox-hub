"""Parco auto: veicoli con assegnatario, scadenze e chilometri; contratti di noleggio o leasing; costi."""
import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from core.mixins import AziendaMixin

SCADENZE = [("assicurazione", "Assicurazione"), ("bollo", "Bollo"), ("revisione", "Revisione"), ("tagliando", "Tagliando")]


class Veicolo(AziendaMixin):
    PROPRIETA, NOLEGGIO, LEASING = "proprieta", "noleggio", "leasing"
    targa = models.CharField("targa", max_length=12)
    modello = models.CharField("marca e modello", max_length=120)
    tipo_possesso = models.CharField("possesso", max_length=10, default=PROPRIETA,
                                     choices=[(PROPRIETA, "Di proprietà"), (NOLEGGIO, "Noleggio a lungo termine"), (LEASING, "Leasing")])
    alimentazione = models.CharField("alimentazione", max_length=12, blank=True,
                                     choices=[("benzina", "Benzina"), ("diesel", "Diesel"), ("ibrida", "Ibrida"), ("elettrica", "Elettrica"), ("gpl", "GPL/Metano")])
    assegnato_a = models.ForeignKey("personale.Dipendente", on_delete=models.SET_NULL, null=True, blank=True, related_name="veicoli",
                                    verbose_name="assegnato a")
    uso_promiscuo = models.BooleanField("uso anche privato", default=False, help_text="fringe benefit in busta paga: informalo al consulente")
    km = models.PositiveIntegerField("chilometri", default=0)
    immatricolato_il = models.DateField("immatricolato il", null=True, blank=True)
    assicurazione_al = models.DateField("assicurazione fino al", null=True, blank=True)
    bollo_al = models.DateField("bollo fino al", null=True, blank=True)
    revisione_al = models.DateField("prossima revisione", null=True, blank=True)
    tagliando_al = models.DateField("prossimo tagliando", null=True, blank=True)
    tagliando_km = models.PositiveIntegerField("tagliando ai km", null=True, blank=True)
    attivo = models.BooleanField("in uso", default=True)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "veicolo"
        verbose_name_plural = "veicoli"
        ordering = ["targa"]
        constraints = [models.UniqueConstraint(fields=["azienda", "targa"], name="flotta_targa_unica")]

    def __str__(self):
        return f"{self.targa} · {self.modello}"

    def clean(self):
        self.targa = "".join(self.targa.split()).upper()

    def scadenze(self, entro=30, oggi=None):
        """[(nome, data, scaduta)] delle scadenze entro `entro` giorni (o già passate)."""
        oggi = oggi or timezone.localdate()
        limite = oggi + datetime.timedelta(days=entro)
        voci = [(n, getattr(self, f"{c}_al")) for c, n in SCADENZE]
        risultato = [(n, d, d < oggi) for n, d in voci if d and d <= limite]
        if self.tagliando_km and self.km >= self.tagliando_km - 500:
            risultato.append(("Tagliando ai km", None, self.km >= self.tagliando_km))
        return risultato


class ContrattoVeicolo(AziendaMixin):
    """Noleggio a lungo termine o leasing: con chi, quanto al mese, fino a quando e quanti km compresi."""
    veicolo = models.ForeignKey(Veicolo, on_delete=models.CASCADE, related_name="contratti", verbose_name="veicolo")
    fornitore = models.ForeignKey("contatti.Contatto", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="società")
    dal = models.DateField("dal")
    al = models.DateField("al")
    canone = models.DecimalField("canone mensile (€)", max_digits=10, decimal_places=2)
    km_compresi = models.PositiveIntegerField("km compresi", null=True, blank=True)
    riscatto = models.DecimalField("riscatto (€)", max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "contratto del veicolo"
        verbose_name_plural = "contratti dei veicoli"
        ordering = ["-dal"]

    def __str__(self):
        return f"{self.veicolo} dal {self.dal:%d/%m/%Y}"

    def clean(self):
        if self.dal and self.al and self.al < self.dal:
            raise ValidationError({"al": "La fine viene dopo l'inizio."})


class CostoVeicolo(AziendaMixin):
    TIPI = [("carburante", "Carburante o ricarica"), ("manutenzione", "Manutenzione"), ("pneumatici", "Pneumatici"),
            ("assicurazione", "Assicurazione"), ("bollo", "Bollo"), ("pedaggi", "Pedaggi e parcheggi"), ("multa", "Multa"), ("altro", "Altro")]
    veicolo = models.ForeignKey(Veicolo, on_delete=models.CASCADE, related_name="costi", verbose_name="veicolo")
    data = models.DateField("data", default=timezone.localdate)
    tipo = models.CharField("tipo", max_length=14, choices=TIPI, default="carburante")
    importo = models.DecimalField("importo (€)", max_digits=10, decimal_places=2)
    km = models.PositiveIntegerField("km al momento", null=True, blank=True, help_text="aggiorna i chilometri del veicolo")
    litri = models.DecimalField("litri o kWh", max_digits=8, decimal_places=2, null=True, blank=True)
    descrizione = models.CharField("descrizione", max_length=200, blank=True)
    dipendente = models.ForeignKey("personale.Dipendente", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="chi")

    class Meta(AziendaMixin.Meta):
        verbose_name = "costo del veicolo"
        verbose_name_plural = "costi dei veicoli"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.importo} € · {self.veicolo.targa}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.km and self.km > self.veicolo.km:
            Veicolo.objects.filter(pk=self.veicolo_id).update(km=self.km)


def riepilogo_costi(veicolo, anno=None):
    anno = anno or timezone.localdate().year
    costi = veicolo.costi.filter(data__year=anno)
    totale = costi.aggregate(t=Sum("importo"))["t"] or Decimal(0)
    canoni = Decimal(0)
    for c in veicolo.contratti.all():
        inizio, fine = max(c.dal, datetime.date(anno, 1, 1)), min(c.al, datetime.date(anno, 12, 31))
        if fine >= inizio:
            mesi = (fine.year - inizio.year) * 12 + fine.month - inizio.month + 1
            canoni += c.canone * mesi
    per_tipo = {r["tipo"]: r["t"] for r in costi.values("tipo").annotate(t=Sum("importo"))}
    return {"anno": anno, "costi": totale, "canoni": canoni, "totale": totale + canoni,
            "per_tipo": [(dict(CostoVeicolo.TIPI)[k], v) for k, v in sorted(per_tipo.items(), key=lambda x: -x[1])]}
