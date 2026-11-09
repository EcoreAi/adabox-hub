from decimal import Decimal

from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin
from fiscale import calcoli


class DatiFiscali(models.Model):
    """Dati dell'azienda che emette le fatture (estensione uno-a-uno di core.Azienda)."""
    REGIMI = [("RF01", "RF01 · Ordinario"), ("RF02", "RF02 · Contribuenti minimi"), ("RF04", "RF04 · Agricoltura e pesca"),
              ("RF05", "RF05 · Vendita di sali e tabacchi"), ("RF06", "RF06 · Commercio di fiammiferi"),
              ("RF07", "RF07 · Editoria"), ("RF08", "RF08 · Telefonia pubblica"),
              ("RF09", "RF09 · Rivendita di documenti di trasporto e sosta"), ("RF10", "RF10 · Intrattenimenti e giochi"),
              ("RF11", "RF11 · Agenzie di viaggi e turismo"), ("RF12", "RF12 · Agriturismo"),
              ("RF13", "RF13 · Vendite a domicilio"), ("RF14", "RF14 · Beni usati e oggetti d'arte"),
              ("RF15", "RF15 · Agenzie di vendite all'asta"), ("RF16", "RF16 · IVA per cassa della PA"),
              ("RF17", "RF17 · IVA per cassa"), ("RF18", "RF18 · Altro"), ("RF19", "RF19 · Forfettario")]
    azienda = models.OneToOneField("core.Azienda", on_delete=models.CASCADE, related_name="dati_fiscali",
                                   verbose_name="azienda")
    regime_fiscale = models.CharField("regime fiscale", max_length=4, choices=REGIMI, default="RF01")
    iban = models.CharField("IBAN", max_length=34, blank=True)
    banca = models.CharField("banca", max_length=80, blank=True)
    rea_ufficio = models.CharField("REA: provincia dell'ufficio", max_length=2, blank=True)
    rea_numero = models.CharField("REA: numero", max_length=20, blank=True)
    capitale_sociale = models.DecimalField("capitale sociale", max_digits=14, decimal_places=2, null=True, blank=True)
    socio_unico = models.CharField("soci", max_length=2, blank=True,
                                   choices=[("", "—"), ("SU", "Socio unico"), ("SM", "Più soci")])
    bollo_al_cliente = models.BooleanField("addebita il bollo al cliente", default=False,
                                           help_text="aggiunge alla fattura una riga esclusa da IVA con i 2 € del bollo")
    progressivo_invio = models.PositiveIntegerField("ultimo progressivo di invio", default=0, editable=False)

    class Meta:
        verbose_name = "dati fiscali"
        verbose_name_plural = "dati fiscali"

    def __str__(self):
        return f"Dati fiscali di {self.azienda}"


class Fattura(AziendaMixin, ProprietaMixin):
    FATTURA, NOTA_CREDITO, NOTA_DEBITO, PARCELLA = "TD01", "TD04", "TD05", "TD06"
    TIPI = [(FATTURA, "Fattura"), ("TD24", "Fattura differita (con DDT)"), ("TD25", "Fattura differita triangolare"),
            ("TD02", "Acconto su fattura"), (PARCELLA, "Parcella"), ("TD03", "Acconto su parcella"),
            (NOTA_CREDITO, "Nota di credito"), (NOTA_DEBITO, "Nota di debito"),
            ("TD26", "Cessione di beni ammortizzabili"),
            ("TD16", "Autofattura: reverse charge interno"), ("TD17", "Autofattura: servizi dall'estero"),
            ("TD18", "Autofattura: beni intra-UE"), ("TD19", "Autofattura: beni già in Italia"),
            ("TD28", "Autofattura: acquisti da San Marino"), ("TD20", "Autofattura: regolarizzazione"),
            ("TD21", "Autofattura: splafonamento"), ("TD27", "Autofattura: autoconsumo o omaggi")]
    # il fornitore è il cedente, noi il cessionario: nell'XML i ruoli si scambiano
    SCAMBIO_RUOLI = {"TD16", "TD17", "TD18", "TD19", "TD20", "TD28"}
    AUTOFATTURE = SCAMBIO_RUOLI | {"TD21", "TD27"}
    CON_DDT = {"TD24", "TD25"}
    STORNABILI = {FATTURA, "TD24", "TD25", "TD02", PARCELLA, "TD03", NOTA_DEBITO, "TD26"}
    BOLLO_AUTO, BOLLO_SI, BOLLO_NO = "auto", "si", "no"
    IMPORTO_BOLLO, SOGLIA_BOLLO = Decimal("2.00"), Decimal("77.47")
    # nature senza IVA che pagano il bollo sopra la soglia; export, intra e San Marino no, reverse charge no
    NATURE_BOLLO = {"N1", "N2.1", "N2.2", "N3.4", "N3.5", "N3.6", "N4"}
    RIFERIMENTI = [("ordine", "Ordine d'acquisto"), ("contratto", "Contratto"), ("convenzione", "Convenzione"),
                   ("ricezione", "Ricezione")]
    BOZZA, EMESSA, ANNULLATA = "bozza", "emessa", "annullata"
    STATI = [(BOZZA, "Bozza"), (EMESSA, "Emessa"), (ANNULLATA, "Annullata")]
    tipo = models.CharField("tipo di documento", max_length=4, choices=TIPI, default=FATTURA)
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=BOZZA, editable=False)
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="fatture",
                                verbose_name="cliente")
    data = models.DateField("data", default=timezone.localdate)
    termine_pagamento = models.ForeignKey("fiscale.TerminePagamento", on_delete=models.SET_NULL, null=True, blank=True,
                                          verbose_name="pagamento")
    ordine = models.ForeignKey("vendite.OrdineVendita", on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="fatture", verbose_name="ordine di vendita", editable=False)
    fattura_origine = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True,
                                        related_name="note_credito", verbose_name="fattura stornata", editable=False)
    causale = models.CharField("causale", max_length=200, blank=True)
    note = models.TextField("note", blank=True)
    collegata_numero = models.CharField("documento collegato: numero", max_length=20, blank=True,
                                        help_text="la fattura del fornitore che l'autofattura integra")
    collegata_data = models.DateField("documento collegato: data", null=True, blank=True)
    rif_tipo = models.CharField("riferimento", max_length=12, choices=RIFERIMENTI, default="ordine", blank=True)
    rif_numero = models.CharField("numero del riferimento", max_length=20, blank=True,
                                  help_text="ordine o contratto della PA: serve per indicare CIG e CUP")
    rif_data = models.DateField("data del riferimento", null=True, blank=True)
    cig = models.CharField("CIG", max_length=15, blank=True)
    cup = models.CharField("CUP", max_length=15, blank=True)
    commessa = models.CharField("codice commessa", max_length=100, blank=True)
    bollo_modo = models.CharField("imposta di bollo", max_length=4, default=BOLLO_AUTO, blank=True,
                                  choices=[(BOLLO_AUTO, "Automatica (oltre 77,47 € senza IVA)"), (BOLLO_SI, "Sempre"),
                                           (BOLLO_NO, "Mai")])
    bollo = models.DecimalField("bollo", max_digits=6, decimal_places=2, default=0, editable=False)
    ritenute = models.DecimalField("ritenute", max_digits=14, decimal_places=2, default=0, editable=False)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2, default=0, editable=False)
    imposta = models.DecimalField("IVA", max_digits=14, decimal_places=2, default=0, editable=False)
    totale = models.DecimalField("totale", max_digits=14, decimal_places=2, default=0, editable=False)
    pagata = models.BooleanField("incassata", default=False, editable=False)
    emessa_il = models.DateTimeField("emessa il", null=True, blank=True, editable=False)
    progressivo_invio = models.CharField("progressivo di invio", max_length=5, blank=True, editable=False,
                                         help_text="assegnato alla prima generazione dell'XML")

    class Meta(AziendaMixin.Meta):
        verbose_name = "fattura"
        verbose_name_plural = "fatture"
        ordering = ["-data", "-pk"]

    def __str__(self):
        prefisso = {self.FATTURA: "Fattura"}.get(self.tipo) or self.get_tipo_display().split(":")[0].split(" (")[0]
        return f"{prefisso} {self.numero}" if self.numero else f"{prefisso} in bozza {self.pk}"

    @property
    def modificabile(self):
        return self.stato == self.BOZZA

    @property
    def segno(self):
        return Decimal(-1) if self.tipo == self.NOTA_CREDITO else Decimal(1)

    @property
    def autofattura(self):
        return self.tipo in self.AUTOFATTURE

    @property
    def incassabile(self):
        """Note di credito e autofatture non hanno scadenze: nessuno paga quel documento."""
        return self.tipo != self.NOTA_CREDITO and not self.autofattura

    def riepilogo_iva(self):
        return calcoli.riepilogo_iva([(r.importo, r.aliquota) for r in self.righe.select_related("aliquota")]
                                     + [(c.importo, c.aliquota) for c in self.casse.select_related("aliquota")])

    def bollo_dovuto(self):
        if self.bollo_modo == self.BOLLO_NO:
            return Decimal(0)
        if self.bollo_modo == self.BOLLO_SI:
            return self.IMPORTO_BOLLO
        esente = sum((r.importo for r in self.righe.select_related("aliquota")
                      if not r.is_bollo and r.aliquota and r.aliquota.natura in self.NATURE_BOLLO), Decimal(0))
        return self.IMPORTO_BOLLO if esente > self.SOGLIA_BOLLO else Decimal(0)

    @property
    def incassato(self):
        return sum((s.incassato for s in self.scadenze.all()), Decimal(0))

    @property
    def residuo(self):
        return sum((s.residuo for s in self.scadenze.all()), Decimal(0))

    @property
    def percentuale_incassata(self):
        dovuto = sum((s.importo for s in self.scadenze.all()), Decimal(0))
        return int(self.incassato * 100 / dovuto) if dovuto else 100

    @property
    def iva_in_scissione(self):
        """IVA che il cliente versa direttamente all'Erario (split payment): non si incassa."""
        return sum((g["imposta"] for g in self.riepilogo_iva() if g["aliquota"].esigibilita == g["aliquota"].SCISSIONE),
                   Decimal(0))

    @property
    def da_incassare(self):
        """Quello che il cliente paga davvero: senza l'IVA in scissione e senza le ritenute che versa lui."""
        return self.totale - self.iva_in_scissione - self.ritenute

    @property
    def stornata(self):
        """Interamente stornata da note di credito emesse."""
        note = self.note_credito.filter(stato=self.EMESSA).aggregate(t=models.Sum("totale"))["t"] or Decimal(0)
        return self.stato == self.EMESSA and note >= self.totale

    def ricalcola(self):
        righe = list(self.righe.select_related("aliquota"))
        base_cassa = sum((r.importo for r in righe), Decimal(0))
        casse = list(self.casse.select_related("aliquota"))
        for c in casse:
            c.imponibile, c.importo = base_cassa, calcoli.arrotonda(base_cassa * c.aliquota_cassa / 100)
            c.save(update_fields=["imponibile", "importo"])
        base_ritenuta = sum((r.importo for r in righe if r.soggetta_ritenuta), Decimal(0)) + sum(
            (c.importo for c in casse if c.soggetta_ritenuta), Decimal(0))
        totale_ritenute = Decimal(0)
        for r in self.righe_ritenuta.all():
            r.imponibile = calcoli.arrotonda(base_ritenuta * r.percentuale_base / 100)
            r.importo = calcoli.arrotonda(r.imponibile * r.aliquota_ritenuta / 100)
            r.save(update_fields=["imponibile", "importo"])
            totale_ritenute += r.importo
        self.imponibile, self.imposta, self.totale = calcoli.totali(
            [(r.importo, r.aliquota) for r in righe] + [(c.importo, c.aliquota) for c in casse])
        self.ritenute, self.bollo = totale_ritenute, self.bollo_dovuto()
        self.save(update_fields=["imponibile", "imposta", "totale", "ritenute", "bollo"])


class RigaFattura(models.Model):
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="righe", verbose_name="fattura")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    unita = models.ForeignKey("prodotti.UnitaMisura", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                              verbose_name="unità", help_text="vuoto = quella del prodotto")
    quantita_base = models.DecimalField("quantità nell'unità del prodotto", max_digits=14, decimal_places=3, null=True, blank=True,
                                        editable=False)
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4, null=True, blank=True)
    sconto = models.DecimalField("sconto %", max_digits=5, decimal_places=2, default=0)
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="IVA")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0, editable=False)
    soggetta_ritenuta = models.BooleanField("soggetta a ritenuta", default=True, editable=False)
    is_bollo = models.BooleanField("riga del bollo", default=False, editable=False)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]

    def clean(self):
        from django.core.exceptions import ValidationError
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
        prepara_riga(self, "vendita")
        if self.prodotto_id:
            self.descrizione = self.descrizione or (self.prodotto.descrizione_vendita or self.prodotto.nome)[:250]
            if self.prezzo is None:
                self.prezzo = self.prodotto.prezzo_vendita * self.per_unita
            if self.aliquota_id is None:
                self.aliquota = self.prodotto.aliquota_iva
        if self.aliquota_id is None:
            self.aliquota = AliquotaIva.objects.filter(codice="22").first()
        self.prezzo = self.prezzo if self.prezzo is not None else Decimal(0)
        self.importo = calcoli.importo_riga(self.quantita, self.prezzo, self.sconto)
        super().save(*args, **kwargs)


class Ritenuta(models.Model):
    """Ritenuta d'acconto, Enasarco, INPS… che il cliente trattiene e versa al posto nostro."""
    TIPI = [("RT01", "Ritenuta d'acconto, persone fisiche"), ("RT02", "Ritenuta d'acconto, persone giuridiche"),
            ("RT03", "Contributo INPS"), ("RT04", "Contributo ENASARCO"), ("RT05", "Contributo ENPAM"),
            ("RT06", "Altro contributo previdenziale")]
    CAUSALI = [(c, c) for c in ("A", "B", "C", "D", "E", "G", "H", "I", "J", "L", "L1", "M", "M1", "M2", "N", "O", "O1",
                                "P", "Q", "R", "S", "T", "U", "V", "V1", "V2", "W", "X", "Y", "ZO")]
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="righe_ritenuta", verbose_name="fattura")
    tipo = models.CharField("tipo", max_length=4, choices=TIPI, default="RT01")
    aliquota_ritenuta = models.DecimalField("aliquota %", max_digits=5, decimal_places=2, default=Decimal("20"))
    percentuale_base = models.DecimalField("sul % dell'imponibile", max_digits=5, decimal_places=2, default=Decimal("100"),
                                           help_text="es. 50 per gli agenti con dipendenti, 100 per i professionisti")
    causale = models.CharField("causale (CU)", max_length=2, choices=CAUSALI, default="A")
    imponibile = models.DecimalField("base", max_digits=14, decimal_places=2, default=0, editable=False)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = "ritenuta"
        verbose_name_plural = "ritenute"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.aliquota_ritenuta}%"


class CassaPrevidenziale(models.Model):
    """Contributo della cassa dei professionisti: si somma all'imponibile e paga l'IVA dell'aliquota indicata."""
    TIPI = [("TC01", "Avvocati"), ("TC02", "Dottori commercialisti"), ("TC03", "Geometri"),
            ("TC04", "Ingegneri e architetti"), ("TC05", "Notai"), ("TC06", "Ragionieri"), ("TC07", "ENASARCO"),
            ("TC08", "ENPACL, consulenti del lavoro"), ("TC09", "ENPAM, medici"), ("TC10", "ENPAF, farmacisti"),
            ("TC11", "ENPAV, veterinari"), ("TC12", "ENPAIA, agricoltura"), ("TC13", "Spedizionieri e marittimi"),
            ("TC14", "INPGI, giornalisti"), ("TC15", "ONAOSI"), ("TC16", "CASAGIT"), ("TC17", "EPPI, periti industriali"),
            ("TC18", "EPAP, pluricategoriale"), ("TC19", "ENPAB, biologi"), ("TC20", "ENPAPI, infermieri"),
            ("TC21", "ENPAP, psicologi"), ("TC22", "INPS")]
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="casse", verbose_name="fattura")
    tipo = models.CharField("cassa", max_length=4, choices=TIPI, default="TC22")
    aliquota_cassa = models.DecimalField("contributo %", max_digits=5, decimal_places=2, default=Decimal("4"))
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, verbose_name="IVA sul contributo")
    soggetta_ritenuta = models.BooleanField("soggetto a ritenuta", default=False)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2, default=0, editable=False)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        verbose_name = "cassa previdenziale"
        verbose_name_plural = "casse previdenziali"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.aliquota_cassa}%"


class RiferimentoDDT(models.Model):
    """DDT citato da una fattura differita."""
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="ddt", verbose_name="fattura")
    numero = models.CharField("numero DDT", max_length=20)
    data = models.DateField("data DDT")

    class Meta:
        verbose_name = "DDT collegato"
        verbose_name_plural = "DDT collegati"
        ordering = ["data", "pk"]

    def __str__(self):
        return f"DDT {self.numero} del {self.data:%d/%m/%Y}"


class Scadenza(models.Model):
    fattura = models.ForeignKey(Fattura, on_delete=models.CASCADE, related_name="scadenze", verbose_name="fattura")
    data = models.DateField("scadenza")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2)
    modalita = models.CharField("modalità", max_length=4, default="MP05")
    incassato = models.DecimalField("incassato", max_digits=14, decimal_places=2, default=0, editable=False)
    pagata = models.BooleanField("incassata", default=False)
    pagata_il = models.DateField("incassata il", null=True, blank=True)

    class Meta:
        verbose_name = "scadenza"
        verbose_name_plural = "scadenze"
        ordering = ["data", "pk"]

    def __str__(self):
        return f"{self.fattura} · {self.data:%d/%m/%Y} · {self.importo} €"

    @property
    def residuo(self):
        return self.importo - self.incassato


class Incasso(models.Model):
    """Soldi arrivati (anche in parte) su una scadenza, oppure scalati con una nota di credito o un abbuono."""
    INCASSO, COMPENSAZIONE, ABBUONO = "incasso", "compensazione", "abbuono"
    TIPI = [(INCASSO, "Incasso"), (COMPENSAZIONE, "Compensazione con nota di credito"), (ABBUONO, "Abbuono")]
    METODI = [("bonifico", "Bonifico"), ("contanti", "Contanti"), ("carta", "Carta"), ("assegno", "Assegno"),
              ("riba", "RIBA"), ("sdd", "Addebito SEPA"), ("altro", "Altro")]
    scadenza = models.ForeignKey(Scadenza, on_delete=models.CASCADE, related_name="incassi", verbose_name="scadenza")
    tipo = models.CharField("tipo", max_length=14, choices=TIPI, default=INCASSO)
    data = models.DateField("data", default=timezone.localdate)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2)
    metodo = models.CharField("metodo", max_length=10, choices=METODI, default="bonifico")
    riferimento = models.CharField("riferimento", max_length=120, blank=True, help_text="es. CRO del bonifico")
    nota_credito = models.ForeignKey(Fattura, on_delete=models.SET_NULL, null=True, blank=True, related_name="compensazioni",
                                     verbose_name="nota di credito")
    utente = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name="registrato da")
    creato = models.DateTimeField("registrato il", auto_now_add=True)

    class Meta:
        verbose_name = "incasso"
        verbose_name_plural = "incassi"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return f"{self.get_tipo_display()} di {self.importo} € del {self.data:%d/%m/%Y}"
