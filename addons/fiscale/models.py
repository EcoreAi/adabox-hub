from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

NATURE = [
    ("", "—"),
    ("N1", "N1 · Escluse ex art. 15"),
    ("N2.1", "N2.1 · Non soggette, artt. da 7 a 7-septies"),
    ("N2.2", "N2.2 · Non soggette, altri casi"),
    ("N3.1", "N3.1 · Non imponibili, esportazioni"),
    ("N3.2", "N3.2 · Non imponibili, cessioni intracomunitarie"),
    ("N3.3", "N3.3 · Non imponibili, cessioni verso San Marino"),
    ("N3.4", "N3.4 · Non imponibili, operazioni assimilate alle esportazioni"),
    ("N3.5", "N3.5 · Non imponibili, dichiarazioni d'intento"),
    ("N3.6", "N3.6 · Non imponibili, altre operazioni"),
    ("N4", "N4 · Esenti"),
    ("N5", "N5 · Regime del margine"),
    ("N6.1", "N6.1 · Inversione contabile, cessione di rottami"),
    ("N6.2", "N6.2 · Inversione contabile, oro e argento"),
    ("N6.3", "N6.3 · Inversione contabile, subappalto edile"),
    ("N6.4", "N6.4 · Inversione contabile, cessione di fabbricati"),
    ("N6.5", "N6.5 · Inversione contabile, telefoni cellulari"),
    ("N6.6", "N6.6 · Inversione contabile, prodotti elettronici"),
    ("N6.7", "N6.7 · Inversione contabile, settore edile"),
    ("N6.8", "N6.8 · Inversione contabile, settore energetico"),
    ("N6.9", "N6.9 · Inversione contabile, altri casi"),
    ("N7", "N7 · IVA assolta in altro stato UE"),
]


class AliquotaIva(models.Model):
    IMMEDIATA, DIFFERITA, SCISSIONE = "I", "D", "S"
    codice = models.CharField("codice", max_length=10, unique=True, help_text="es. 22, 10, N4")
    descrizione = models.CharField("descrizione", max_length=120)
    percentuale = models.DecimalField("percentuale", max_digits=5, decimal_places=2)
    natura = models.CharField("natura", max_length=4, choices=NATURE, blank=True,
                              help_text="obbligatoria per le aliquote allo 0%")
    riferimento_normativo = models.CharField("riferimento normativo", max_length=100, blank=True)
    esigibilita = models.CharField("esigibilità IVA", max_length=1, default=IMMEDIATA,
                                   choices=[(IMMEDIATA, "Immediata"), (DIFFERITA, "Differita"),
                                            (SCISSIONE, "Scissione dei pagamenti")])
    attiva = models.BooleanField("attiva", default=True)

    class Meta:
        verbose_name = "aliquota IVA"
        verbose_name_plural = "aliquote IVA"
        ordering = ["-percentuale", "codice"]

    def __str__(self):
        return self.descrizione

    def clean(self):
        if self.percentuale is not None and self.percentuale < 0:
            raise ValidationError({"percentuale": "La percentuale non può essere negativa."})
        if self.percentuale == 0 and not self.natura:
            raise ValidationError({"natura": "Un'aliquota allo 0% deve indicare la natura dell'operazione."})
        if self.percentuale and self.natura:
            raise ValidationError({"natura": "La natura si indica solo per le aliquote allo 0%."})


class TerminePagamento(models.Model):
    MODALITA = [("MP01", "Contanti"), ("MP02", "Assegno"), ("MP05", "Bonifico"), ("MP08", "Carta di pagamento"),
                ("MP12", "RIBA"), ("MP19", "SEPA Direct Debit")]
    nome = models.CharField("nome", max_length=80, unique=True)
    rate = models.JSONField("rate", default=list,
                            help_text='es. [{"giorni": 30, "percentuale": 50, "fine_mese": true}, …]')
    modalita = models.CharField("modalità di pagamento", max_length=4, choices=MODALITA, default="MP05")
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "termine di pagamento"
        verbose_name_plural = "termini di pagamento"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def clean(self):
        if not isinstance(self.rate, list) or not self.rate:
            raise ValidationError({"rate": "Indica almeno una rata."})
        totale = Decimal(0)
        for r in self.rate:
            if not isinstance(r, dict) or not isinstance(r.get("giorni"), int) or r["giorni"] < 0:
                raise ValidationError({"rate": f"Rata non valida: {r!r} (servono giorni ≥ 0 e percentuale)."})
            totale += Decimal(str(r.get("percentuale", 0)))
        if totale != 100:
            raise ValidationError({"rate": f"Le percentuali delle rate sommano a {totale}, non a 100."})
