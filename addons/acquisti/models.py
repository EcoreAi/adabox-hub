from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from stdnum import iban as stdnum_iban

from core.mixins import AziendaMixin, ProprietaMixin
from fiscale import calcoli


def valida_iban(valore):
    if not stdnum_iban.is_valid(valore):
        raise ValidationError("IBAN non valido.")


class CondizioniFornitore(AziendaMixin):
    """Ciò che vale di norma con un fornitore: lo si propone sugli ordini nuovi, ma l'ordine resta modificabile."""
    fornitore = models.OneToOneField("contatti.Contatto", on_delete=models.CASCADE, related_name="condizioni_acquisto",
                                     limit_choices_to={"fornitore": True}, verbose_name="fornitore")
    termine_pagamento = models.ForeignKey("fiscale.TerminePagamento", on_delete=models.SET_NULL, null=True, blank=True,
                                          verbose_name="pagamento")
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.SET_NULL, null=True, blank=True,
                                 verbose_name="IVA", help_text="se indicata, vale al posto di quella del prodotto "
                                                               "(es. fornitore estero)")
    iban = models.CharField("IBAN", max_length=34, blank=True, validators=[valida_iban])
    giorni_consegna = models.PositiveIntegerField("giorni di consegna", null=True, blank=True,
                                                  help_text="per calcolare la consegna prevista")
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "condizioni del fornitore"
        verbose_name_plural = "condizioni dei fornitori"
        ordering = ["fornitore__nome"]

    def __str__(self):
        return f"Condizioni di {self.fornitore}"

    def save(self, *args, **kwargs):
        self.iban = "".join(self.iban.split()).upper()
        super().save(*args, **kwargs)


class VoceListino(AziendaMixin):
    """Prezzo di un prodotto presso un fornitore. Più voci con minimi diversi fanno gli scaglioni."""
    fornitore = models.ForeignKey("contatti.Contatto", on_delete=models.CASCADE, related_name="listino_acquisto",
                                  limit_choices_to={"fornitore": True}, verbose_name="fornitore")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.CASCADE, related_name="listino_acquisto",
                                 verbose_name="prodotto")
    codice_fornitore = models.CharField("codice del fornitore", max_length=60, blank=True)
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4)
    quantita_minima = models.DecimalField("da quantità", max_digits=12, decimal_places=3, default=1,
                                          help_text="il prezzo vale da questa quantità in su; "
                                                    "la più bassa è il minimo d'ordine")
    giorni_consegna = models.PositiveIntegerField("giorni di consegna", null=True, blank=True)
    valido_dal = models.DateField("valido dal", null=True, blank=True)
    valido_al = models.DateField("valido al", null=True, blank=True)
    preferito = models.BooleanField("preferito", default=False,
                                    help_text="a parità di prodotto, il riordino sceglie questo fornitore")

    class Meta(AziendaMixin.Meta):
        verbose_name = "voce di listino"
        verbose_name_plural = "listini fornitori"
        ordering = ["prodotto__nome", "fornitore__nome", "quantita_minima"]

    def __str__(self):
        return f"{self.prodotto} da {self.fornitore}"

    def clean(self):
        if self.prezzo is not None and self.prezzo < 0:
            raise ValidationError({"prezzo": "Il prezzo non può essere negativo."})
        if self.quantita_minima is not None and self.quantita_minima <= 0:
            raise ValidationError({"quantita_minima": "La quantità deve essere positiva."})
        if self.valido_dal and self.valido_al and self.valido_al < self.valido_dal:
            raise ValidationError({"valido_al": "La fine viene prima dell'inizio."})


class ContrattoQuadro(AziendaMixin):
    """Prezzi e quantità concordati con un fornitore per un periodo; gli ordini di richiamo ne scalano il residuo."""
    BOZZA, ATTIVO, CHIUSO = "bozza", "attivo", "chiuso"
    STATI = [(BOZZA, "Bozza"), (ATTIVO, "Attivo"), (CHIUSO, "Chiuso")]
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    stato = models.CharField("stato", max_length=8, choices=STATI, default=BOZZA, editable=False)
    fornitore = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="contratti_quadro",
                                  limit_choices_to={"fornitore": True}, verbose_name="fornitore")
    dal = models.DateField("dal", default=timezone.localdate)
    al = models.DateField("al", null=True, blank=True)
    riferimento_fornitore = models.CharField("riferimento del fornitore", max_length=100, blank=True)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "contratto quadro"
        verbose_name_plural = "contratti quadro"
        ordering = ["-dal", "-pk"]

    def __str__(self):
        return self.numero or f"Contratto in bozza {self.pk}"

    def clean(self):
        if self.dal and self.al and self.al < self.dal:
            raise ValidationError({"al": "La fine viene prima dell'inizio."})


class RigaContratto(models.Model):
    contratto = models.ForeignKey(ContrattoQuadro, on_delete=models.CASCADE, related_name="righe",
                                  verbose_name="contratto")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, verbose_name="prodotto")
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4)
    quantita = models.DecimalField("quantità concordata", max_digits=12, decimal_places=3, null=True, blank=True,
                                   help_text="vuota = senza limite di quantità")

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]
        constraints = [models.UniqueConstraint(fields=["contratto", "prodotto"], name="acquisti_contratto_prodotto")]

    def __str__(self):
        return str(self.prodotto)


class Gara(AziendaMixin):
    """Richiesta di offerta a più fornitori: ogni offerta è un ordine in bozza, si confrontano e se ne conferma uno."""
    APERTA, AGGIUDICATA, ANNULLATA = "aperta", "aggiudicata", "annullata"
    STATI = [(APERTA, "Aperta"), (AGGIUDICATA, "Aggiudicata"), (ANNULLATA, "Annullata")]
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    titolo = models.CharField("titolo", max_length=200)
    stato = models.CharField("stato", max_length=12, choices=STATI, default=APERTA, editable=False)
    fornitori = models.ManyToManyField("contatti.Contatto", related_name="gare", limit_choices_to={"fornitore": True},
                                       verbose_name="fornitori invitati")
    scadenza = models.DateField("offerte entro", null=True, blank=True)
    vincitore = models.ForeignKey("OrdineAcquisto", on_delete=models.SET_NULL, null=True, blank=True, editable=False,
                                  related_name="+", verbose_name="offerta scelta")
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "gara"
        verbose_name_plural = "gare"
        ordering = ["-pk"]

    def __str__(self):
        return f"{self.numero} · {self.titolo}" if self.numero else self.titolo


class RigaGara(models.Model):
    gara = models.ForeignKey(Gara, on_delete=models.CASCADE, related_name="righe", verbose_name="gara")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]

    def clean(self):
        if not self.prodotto_id and not self.descrizione:
            raise ValidationError("Indica un prodotto o una descrizione.")
        if self.quantita is not None and self.quantita <= 0:
            raise ValidationError({"quantita": "La quantità deve essere positiva."})

    def save(self, *args, **kwargs):
        if self.prodotto_id:
            self.descrizione = self.descrizione or self.prodotto.nome
        super().save(*args, **kwargs)


class OrdineAcquisto(AziendaMixin, ProprietaMixin):
    BOZZA, INVIATO, DA_APPROVARE, CONFERMATO, ANNULLATO = "bozza", "inviato", "da_approvare", "confermato", "annullato"
    STATI = [(BOZZA, "Richiesta"), (INVIATO, "Richiesta inviata"), (DA_APPROVARE, "Da approvare"),
             (CONFERMATO, "Ordine confermato"), (ANNULLATO, "Annullato")]
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    stato = models.CharField("stato", max_length=12, choices=STATI, default=BOZZA, editable=False)
    fornitore = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="ordini_acquisto",
                                  verbose_name="fornitore")
    data = models.DateField("data", default=timezone.localdate)
    consegna_prevista = models.DateField("consegna prevista", null=True, blank=True)
    termine_pagamento = models.ForeignKey("fiscale.TerminePagamento", on_delete=models.SET_NULL, null=True, blank=True,
                                          verbose_name="pagamento")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="ordini_acquisto", verbose_name="buyer")
    riferimento_fornitore = models.CharField("riferimento del fornitore", max_length=100, blank=True)
    consegna_a = models.ForeignKey("contatti.Contatto", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                   verbose_name="spedire a (triangolazione)", help_text="il fornitore spedisce direttamente a questo cliente")
    indirizzo_consegna = models.TextField("indirizzo di consegna", blank=True)
    ordine_vendita_id = models.PositiveBigIntegerField("ordine di vendita", null=True, blank=True, editable=False)
    spedito_il = models.DateField("spedito al cliente il", null=True, blank=True, editable=False)
    note = models.TextField("note per il fornitore", blank=True)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2, default=0, editable=False)
    imposta = models.DecimalField("IVA", max_digits=14, decimal_places=2, default=0, editable=False)
    totale = models.DecimalField("totale", max_digits=14, decimal_places=2, default=0, editable=False)
    confermato_il = models.DateField("confermato il", null=True, blank=True, editable=False)
    contratto = models.ForeignKey(ContrattoQuadro, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="ordini", verbose_name="contratto quadro")
    gara = models.ForeignKey(Gara, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
                             related_name="offerte", verbose_name="gara")

    class Meta(AziendaMixin.Meta):
        verbose_name = "ordine al fornitore"
        verbose_name_plural = "ordini ai fornitori"
        ordering = ["-data", "-pk"]
        permissions = [("approva_ordini", "Può approvare qualunque ordine al fornitore")]

    def __str__(self):
        return self.numero or f"Bozza {self.pk}"

    @property
    def modificabile(self):
        return self.stato in (self.BOZZA, self.INVIATO)

    def clean(self):
        if self.contratto_id and self.fornitore_id and self.contratto.fornitore_id != self.fornitore_id:
            raise ValidationError({"contratto": "Il contratto è con un altro fornitore."})

    def riepilogo_iva(self):
        return calcoli.riepilogo_iva([(r.importo, r.aliquota) for r in self.righe.select_related("aliquota")])

    def ricalcola(self):
        self.imponibile, self.imposta, self.totale = calcoli.totali(
            [(r.importo, r.aliquota) for r in self.righe.select_related("aliquota")])
        self.save(update_fields=["imponibile", "imposta", "totale"])


class RigaAcquisto(models.Model):
    ordine = models.ForeignKey(OrdineAcquisto, on_delete=models.CASCADE, related_name="righe", verbose_name="ordine")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    codice_fornitore = models.CharField("codice del fornitore", max_length=60, blank=True, editable=False)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    unita = models.ForeignKey("prodotti.UnitaMisura", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                              verbose_name="unità", help_text="vuoto = quella del prodotto")
    quantita_base = models.DecimalField("quantità nell'unità del prodotto", max_digits=14, decimal_places=3, null=True, blank=True,
                                        editable=False)
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4, null=True, blank=True,
                                 help_text="vuoto = contratto o listino del fornitore, altrimenti costo del prodotto")
    sconto = models.DecimalField("sconto %", max_digits=5, decimal_places=2, default=0)
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="IVA")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]

    def clean(self):
        if not self.prodotto_id and not self.descrizione:
            raise ValidationError("Indica un prodotto o una descrizione.")
        if self.quantita is not None and self.quantita <= 0:
            raise ValidationError({"quantita": "La quantità deve essere positiva."})
        from prodotti.models import controlla_unita
        controlla_unita(self)

    @property
    def per_unita(self):
        """Quante unità del prodotto vale una unità della riga (1 se è la stessa)."""
        from prodotti.models import converti
        if not self.prodotto_id or not self.unita_id:
            return Decimal(1)
        return converti(Decimal(1), self.unita, self.prodotto.unita) or Decimal(1)

    def save(self, *args, **kwargs):
        from fiscale.models import AliquotaIva

        from prodotti.models import prepara_riga

        from . import listini
        prepara_riga(self, "acquisto")
        if self.prodotto_id:
            self.descrizione = self.descrizione or self.prodotto.nome
            voce = listini.voce(self.ordine.fornitore, self.prodotto, self.quantita_base, self.ordine.data)
            if voce is not None and not self.codice_fornitore:
                self.codice_fornitore = voce.codice_fornitore
            if self.prezzo is None:                    # prezzi per unità del prodotto: riportati all'unità della riga
                base = listini.prezzo_contratto(self.ordine, self.prodotto)
                if base is None and voce is not None:
                    base = voce.prezzo
                if base is None:
                    base = self.prodotto.costo
                self.prezzo = base * self.per_unita if base is not None else None
        if self.aliquota_id is None:
            condizioni = listini.condizioni(self.ordine.fornitore)
            self.aliquota = condizioni.aliquota if condizioni else None
        if self.aliquota_id is None and self.prodotto_id:
            self.aliquota = self.prodotto.aliquota_iva
        if self.aliquota_id is None:
            self.aliquota = AliquotaIva.objects.filter(codice="22").first()
        self.prezzo = self.prezzo if self.prezzo is not None else Decimal(0)
        self.importo = calcoli.importo_riga(self.quantita, self.prezzo, self.sconto)
        super().save(*args, **kwargs)


class RegolaApprovazione(AziendaMixin):
    """Oltre una soglia, o per una categoria, l'ordine deve passare da chi è indicato qui prima di essere confermato."""
    nome = models.CharField("nome", max_length=120)
    livello = models.PositiveSmallIntegerField("livello", default=1,
                                               help_text="si approva in ordine di livello: prima il più basso")
    soglia = models.DecimalField("da imponibile (€)", max_digits=14, decimal_places=2, default=0,
                                 help_text="0 = qualunque importo")
    categoria = models.ForeignKey("prodotti.Categoria", on_delete=models.CASCADE, null=True, blank=True,
                                  verbose_name="solo per la categoria",
                                  help_text="vale se almeno una riga è di questa categoria")
    approvatori = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="regole_approvazione",
                                         verbose_name="approvatori",
                                         help_text="oltre a chi ha il permesso di approvare qualunque ordine")
    attiva = models.BooleanField("attiva", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "regola di approvazione"
        verbose_name_plural = "regole di approvazione"
        ordering = ["livello", "soglia", "pk"]

    def __str__(self):
        return self.nome


class Approvazione(models.Model):
    """Un passaggio di approvazione di un ordine: le righe restano come storia di chi ha deciso e quando."""
    ATTESA, APPROVATA, RIFIUTATA, SUPERATA = "attesa", "approvata", "rifiutata", "superata"
    ESITI = [(ATTESA, "In attesa"), (APPROVATA, "Approvata"), (RIFIUTATA, "Rifiutata"), (SUPERATA, "Non più valida")]
    ordine = models.ForeignKey(OrdineAcquisto, on_delete=models.CASCADE, related_name="approvazioni",
                               verbose_name="ordine")
    regola = models.ForeignKey(RegolaApprovazione, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="regola")
    nome_regola = models.CharField("regola", max_length=120)
    livello = models.PositiveSmallIntegerField("livello", default=1)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2, default=0)
    richiesta_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="richiesta da")
    richiesta_il = models.DateTimeField("richiesta il", default=timezone.now)
    esito = models.CharField("esito", max_length=10, choices=ESITI, default=ATTESA)
    decisa_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="decisa da")
    decisa_il = models.DateTimeField("decisa il", null=True, blank=True)

    class Meta:
        verbose_name = "approvazione"
        verbose_name_plural = "approvazioni"
        ordering = ["livello", "pk"]

    def __str__(self):
        return f"{self.nome_regola}: {self.get_esito_display()}"


class RegolaRiordino(AziendaMixin):
    """Punto di riordino e quantità obiettivo di un bene; senza regola vale la scorta minima del prodotto."""
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.CASCADE, related_name="regole_riordino",
                                 limit_choices_to={"tipo": "bene"}, verbose_name="prodotto")
    punto_riordino = models.DecimalField("riordina sotto", max_digits=12, decimal_places=3)
    scorta_obiettivo = models.DecimalField("riporta a", max_digits=12, decimal_places=3)
    fornitore = models.ForeignKey("contatti.Contatto", on_delete=models.SET_NULL, null=True, blank=True,
                                  limit_choices_to={"fornitore": True}, verbose_name="fornitore",
                                  help_text="vuoto = il preferito o il meno caro del listino")
    automatica = models.BooleanField("crea da sola le richieste", default=False,
                                     help_text="ogni mattina una richiesta in bozza: non parte nulla senza un buyer")

    class Meta(AziendaMixin.Meta):
        verbose_name = "regola di riordino"
        verbose_name_plural = "regole di riordino"
        ordering = ["prodotto__nome"]
        constraints = [models.UniqueConstraint(fields=["azienda", "prodotto"], name="acquisti_riordino_unico")]

    def __str__(self):
        return f"Riordino di {self.prodotto}"

    def clean(self):
        if self.punto_riordino is not None and self.punto_riordino < 0:
            raise ValidationError({"punto_riordino": "Non può essere negativo."})
        if None not in (self.punto_riordino, self.scorta_obiettivo) and self.scorta_obiettivo < self.punto_riordino:
            raise ValidationError({"scorta_obiettivo": "Deve essere almeno pari al punto di riordino."})


class FatturaOrdine(models.Model):
    """Una fattura ricevuta (sdi.FatturaPassiva) imputata a un ordine: il terzo lato del riscontro.
    L'identificativo è un numero perché lo SDI è un modulo facoltativo: gli Acquisti non ne dipendono."""
    ordine = models.ForeignKey(OrdineAcquisto, on_delete=models.CASCADE, related_name="fatture", verbose_name="ordine")
    fattura_id = models.PositiveBigIntegerField("fattura", db_index=True)
    importo = models.DecimalField("imponibile imputato", max_digits=14, decimal_places=2,
                                  help_text="negativo per una nota di credito")
    automatico = models.BooleanField("collegata in automatico", default=False)
    creato_il = models.DateTimeField("collegata il", auto_now_add=True)

    class Meta:
        verbose_name = "fattura dell'ordine"
        verbose_name_plural = "fatture dell'ordine"
        ordering = ["pk"]
        constraints = [models.UniqueConstraint(fields=["ordine", "fattura_id"], name="acquisti_fattura_ordine")]
