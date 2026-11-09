from decimal import Decimal

from django.conf import settings
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin
from fiscale import calcoli


class OrdineVendita(AziendaMixin, ProprietaMixin):
    BOZZA, INVIATO, CONFERMATO, ANNULLATO = "bozza", "inviato", "confermato", "annullato"
    ACCETTATO, RIFIUTATO = "accettato", "rifiutato"
    STATI = [(BOZZA, "Preventivo"), (INVIATO, "Preventivo inviato"), (CONFERMATO, "Ordine confermato"),
             (ANNULLATO, "Annullato")]
    numero = models.CharField("numero preventivo", max_length=30, blank=True, editable=False, db_index=True)
    numero_ordine = models.CharField("numero ordine", max_length=30, blank=True, editable=False, db_index=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=BOZZA, editable=False)
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="ordini_vendita",
                                verbose_name="cliente")
    data = models.DateField("data", default=timezone.localdate)
    validita = models.DateField("valido fino al", null=True, blank=True)
    listino = models.ForeignKey("prodotti.Listino", on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name="listino")
    termine_pagamento = models.ForeignKey("fiscale.TerminePagamento", on_delete=models.SET_NULL, null=True, blank=True,
                                          verbose_name="pagamento")
    commerciale = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="ordini_vendita", verbose_name="commerciale")
    riferimento_cliente = models.CharField("riferimento del cliente", max_length=100, blank=True)
    note = models.TextField("note per il cliente", blank=True)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2, default=0, editable=False)
    imposta = models.DecimalField("IVA", max_digits=14, decimal_places=2, default=0, editable=False)
    totale = models.DecimalField("totale", max_digits=14, decimal_places=2, default=0, editable=False)
    confermato_il = models.DateField("confermato il", null=True, blank=True, editable=False)
    risposta = models.CharField("risposta del cliente", max_length=10, blank=True, editable=False,
                                choices=[(ACCETTATO, "Accettato online"), (RIFIUTATO, "Rifiutato online")])
    risposta_il = models.DateTimeField("risposta il", null=True, blank=True, editable=False)
    risposta_nome = models.CharField("accettato da", max_length=120, blank=True, editable=False)
    risposta_ip = models.GenericIPAddressField("indirizzo IP", null=True, blank=True, editable=False)
    risposta_motivo = models.TextField("motivo del rifiuto", blank=True, editable=False)
    risposta_impronta = models.CharField("impronta del documento accettato", max_length=32, blank=True, editable=False)
    indirizzo_consegna = models.ForeignKey("contatti.IndirizzoContatto", on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name="+", verbose_name="indirizzo di consegna",
                                           help_text="vuoto = la sede del cliente, o il suo indirizzo di consegna predefinito")
    opportunita_id = models.PositiveBigIntegerField("opportunità di origine", null=True, blank=True, editable=False, db_index=True,
                                                    help_text="l'opportunità del CRM da cui nasce il preventivo")

    class Meta(AziendaMixin.Meta):
        verbose_name = "preventivo / ordine"
        verbose_name_plural = "preventivi e ordini"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return self.numero_ordine or self.numero or f"Bozza {self.pk}"

    @property
    def modificabile(self):
        return self.stato in (self.BOZZA, self.INVIATO)

    @property
    def titolo_documento(self):
        return "Ordine" if self.stato == self.CONFERMATO else "Preventivo"

    def righe_valide(self):
        """Le righe che contano: le opzionali solo se il cliente le ha scelte."""
        return [r for r in self.righe.select_related("aliquota") if not r.opzionale or r.scelta]

    def riepilogo_iva(self):
        return calcoli.riepilogo_iva([(r.importo, r.aliquota) for r in self.righe_valide()])

    def ricalcola(self):
        self.imponibile, self.imposta, self.totale = calcoli.totali([(r.importo, r.aliquota) for r in self.righe_valide()])
        self.save(update_fields=["imponibile", "imposta", "totale"])

    def clean(self):
        if self.validita and self.data and self.validita < self.data:
            raise ValidationError({"validita": "La validità non può precedere la data del preventivo."})
        if self.indirizzo_consegna_id and self.cliente_id and self.indirizzo_consegna.contatto_id != self.cliente_id:
            raise ValidationError({"indirizzo_consegna": "L'indirizzo è di un altro contatto."})

    def save(self, *args, **kwargs):
        if self._state.adding and self.listino_id is None and self.cliente_id:      # il listino del cliente, se ne ha uno
            condizioni = CondizioniCliente.objects.filter(contatto_id=self.cliente_id).first()
            if condizioni is not None and condizioni.listino_id:
                self.listino_id = condizioni.listino_id
        super().save(*args, **kwargs)


class RigaVendita(models.Model):
    ordine = models.ForeignKey(OrdineVendita, on_delete=models.CASCADE, related_name="righe", verbose_name="ordine")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    unita = models.ForeignKey("prodotti.UnitaMisura", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                              verbose_name="unità", help_text="vuoto = quella del prodotto")
    quantita_base = models.DecimalField("quantità nell'unità del prodotto", max_digits=14, decimal_places=3, null=True, blank=True,
                                        editable=False)
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4, null=True, blank=True,
                                 help_text="vuoto = dal listino o dal prodotto")
    sconto = models.DecimalField("sconto %", max_digits=5, decimal_places=2, default=0)
    aliquota = models.ForeignKey("fiscale.AliquotaIva", on_delete=models.PROTECT, null=True, blank=True,
                                 verbose_name="IVA")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0, editable=False)
    opzionale = models.BooleanField("opzionale", default=False, help_text="non conta nel totale finché il cliente non la sceglie")
    diretta = models.BooleanField("spedisce il fornitore", default=False,
                                  help_text="triangolazione: alla conferma nasce l'ordine al fornitore, che spedisce al cliente; il magazzino non si muove")
    scelta = models.BooleanField("scelta dal cliente", default=False, editable=False)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["pk"]

    def __str__(self):
        return self.descrizione

    def clean(self):
        if not self.prodotto_id and not self.descrizione:
            raise ValidationError("Indica un prodotto o una descrizione.")
        if self.quantita is not None and self.quantita <= 0:
            raise ValidationError({"quantita": "La quantità deve essere positiva."})
        if self.sconto is not None and not 0 <= self.sconto <= 100:
            raise ValidationError({"sconto": "Lo sconto va da 0 a 100."})
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
        """Valori mancanti dal prodotto e dal listino del documento; importo ricalcolato."""
        from fiscale.models import AliquotaIva
        from prodotti.models import prepara_riga
        from prodotti.prezzi import prezzo
        prepara_riga(self, "vendita")
        if self.prodotto_id:
            if not self.descrizione:
                self.descrizione = (self.prodotto.descrizione_vendita or self.prodotto.nome)[:250]
            dal_listino = self.prezzo is None
            if dal_listino:                            # il listino è per unità del prodotto: riportato all'unità della riga
                self.prezzo = prezzo(self.prodotto, self.ordine.listino, self.quantita_base, self.ordine.data) * self.per_unita
                if self._state.adding and not self.sconto:  # sconto automatico solo sui prezzi che decide il sistema
                    self.sconto = sconto_per(self.ordine.cliente, self.prodotto, self.quantita_base, self.ordine.data) or self.sconto
                if self.ordine.listino_id and self.ordine.listino.iva_inclusa and apps.is_installed("fatturazione"):
                    from fatturazione.posizioni import scorporo
                    self.prezzo = scorporo(self.prezzo, self.prodotto.aliquota_iva)
            if self.aliquota_id is None:
                self.aliquota = self.prodotto.aliquota_iva
                if apps.is_installed("fatturazione"):      # posizione fiscale e dichiarazione d'intento del cliente
                    from fatturazione.posizioni import aliquota_per
                    self.aliquota = aliquota_per(self.ordine.cliente, self.prodotto, self.aliquota, self.ordine.data)
        if self.aliquota_id is None:
            self.aliquota = AliquotaIva.objects.filter(codice="22").first()
        self.prezzo = self.prezzo if self.prezzo is not None else Decimal(0)
        self.importo = calcoli.importo_riga(self.quantita, self.prezzo, self.sconto)
        super().save(*args, **kwargs)


class CondizioniCliente(AziendaMixin):
    """Listino e sconto generale di un cliente: i suoi ordini nascono con il suo listino."""
    contatto = models.OneToOneField("contatti.Contatto", on_delete=models.CASCADE, related_name="condizioni_vendita", verbose_name="cliente")
    listino = models.ForeignKey("prodotti.Listino", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="listino")
    sconto = models.DecimalField("sconto generale %", max_digits=5, decimal_places=2, default=0,
                                 help_text="vale sulle righe senza una regola di sconto più precisa")

    class Meta(AziendaMixin.Meta):
        verbose_name = "condizioni di vendita del cliente"
        verbose_name_plural = "condizioni di vendita dei clienti"

    def __str__(self):
        return f"{self.contatto}: {self.listino or 'listino base'}"


class RegolaSconto(AziendaMixin):
    """Uno sconto automatico sulle righe d'ordine: per un cliente o per tutti, su un prodotto, una categoria o tutto,
    da una quantità, in un periodo. Vince la regola più precisa."""
    nome = models.CharField("nome", max_length=80)
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.CASCADE, null=True, blank=True, related_name="regole_sconto",
                                verbose_name="cliente", help_text="vuoto = tutti i clienti")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.CASCADE, null=True, blank=True, related_name="+", verbose_name="prodotto")
    categoria = models.ForeignKey("prodotti.Categoria", on_delete=models.CASCADE, null=True, blank=True, related_name="+",
                                  verbose_name="categoria", help_text="vale se non c'è il prodotto")
    quantita_minima = models.DecimalField("da quantità", max_digits=12, decimal_places=3, default=1)
    sconto = models.DecimalField("sconto %", max_digits=5, decimal_places=2)
    dal = models.DateField("dal", null=True, blank=True)
    al = models.DateField("al", null=True, blank=True)
    attiva = models.BooleanField("attiva", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "regola di sconto"
        verbose_name_plural = "regole di sconto"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.sconto}%)"

    def clean(self):
        if self.sconto is not None and not 0 < self.sconto <= 100:
            raise ValidationError({"sconto": "Lo sconto va da 0 a 100."})
        if self.dal and self.al and self.al < self.dal:
            raise ValidationError({"al": "La fine viene dopo l'inizio."})


def sconto_per(cliente, prodotto, quantita, data):
    """Lo sconto della regola più precisa (cliente, poi prodotto, poi categoria, poi quantità), o quello generale del cliente."""
    from django.db.models import Q
    if cliente is None or prodotto is None:
        return None
    regole = (RegolaSconto.objects.filter(azienda_id=cliente.azienda_id, attiva=True, quantita_minima__lte=quantita or 1)
              .filter(Q(cliente=cliente) | Q(cliente__isnull=True))
              .filter(Q(prodotto=prodotto) | Q(prodotto_id=prodotto.variante_di_id) | Q(prodotto__isnull=True))
              .filter(Q(categoria_id=prodotto.categoria_id) | Q(categoria__isnull=True))
              .filter(Q(dal__isnull=True) | Q(dal__lte=data), Q(al__isnull=True) | Q(al__gte=data)))
    # una regola sulla variante vince su quella del suo modello, che vale per tutte le varianti
    migliore = sorted(regole, key=lambda r: (r.cliente_id is not None, r.prodotto_id is not None, r.prodotto_id == prodotto.pk,
                                             r.categoria_id is not None,
                                             r.quantita_minima, r.sconto), reverse=True)
    if migliore:
        return migliore[0].sconto
    condizioni = CondizioniCliente.objects.filter(contatto=cliente).first()
    return condizioni.sconto if condizioni and condizioni.sconto else None


class ModelloPreventivo(AziendaMixin):
    """Un preventivo che si ripete: righe (anche opzionali) e testo per il cliente già pronti, da applicare a una bozza."""
    nome = models.CharField("nome", max_length=100)
    note = models.TextField("testo per il cliente", blank=True, help_text="va nelle note del preventivo")
    giorni_validita = models.PositiveIntegerField("valido per giorni", null=True, blank=True)
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "modello di preventivo"
        verbose_name_plural = "modelli di preventivo"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class RigaModelloPreventivo(models.Model):
    modello = models.ForeignKey(ModelloPreventivo, on_delete=models.CASCADE, related_name="righe", verbose_name="modello")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="prodotto")
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    quantita = models.DecimalField("quantità", max_digits=12, decimal_places=3, default=1)
    prezzo = models.DecimalField("prezzo (€)", max_digits=12, decimal_places=4, null=True, blank=True, help_text="vuoto = dal listino")
    sconto = models.DecimalField("sconto %", max_digits=5, decimal_places=2, default=0)
    opzionale = models.BooleanField("opzionale", default=False)

    class Meta:
        verbose_name = "riga del modello"
        verbose_name_plural = "righe del modello"
        ordering = ["pk"]

    def clean(self):
        if not self.prodotto_id and not self.descrizione:
            raise ValidationError("Indica un prodotto o una descrizione.")


class PianoProvvigioni(AziendaMixin):
    """Quanto prende un commerciale sul venduto: percentuale di base, regole per prodotto o categoria, maturazione
    alla conferma dell'ordine o all'incasso della fattura, maggiorazione se raggiunge la quota del periodo."""
    ORDINE, INCASSO = "ordine", "incasso"
    MATURAZIONI = [(ORDINE, "Alla conferma dell'ordine"), (INCASSO, "All'incasso della fattura")]
    nome = models.CharField("nome", max_length=80)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="piani_provvigioni",
                               verbose_name="commerciale", help_text="vuoto = vale per tutti i commerciali senza un piano proprio")
    percentuale = models.DecimalField("provvigione di base (%)", max_digits=5, decimal_places=2, default=0)
    maturazione = models.CharField("matura", max_length=8, choices=MATURAZIONI, default=ORDINE)
    maggiorazione = models.DecimalField("in più a quota raggiunta (%)", max_digits=5, decimal_places=2, default=0,
                                        help_text="punti percentuali in più sul venduto del periodo se il commerciale raggiunge il suo obiettivo")
    dal = models.DateField("valido dal", null=True, blank=True)
    al = models.DateField("valido fino al", null=True, blank=True)
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "piano provvigionale"
        verbose_name_plural = "piani provvigionali"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def percentuale_per(self, prodotto, regole=None):
        regole = list(self.regole.all()) if regole is None else regole
        if prodotto is not None:
            for r in regole:
                if r.prodotto_id == prodotto.pk:
                    return r.percentuale
            for r in regole:
                if r.categoria_id and r.prodotto_id is None and r.categoria_id == prodotto.categoria_id:
                    return r.percentuale
        return self.percentuale


class RegolaProvvigione(models.Model):
    piano = models.ForeignKey(PianoProvvigioni, on_delete=models.CASCADE, related_name="regole", verbose_name="piano")
    prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.CASCADE, null=True, blank=True, related_name="+", verbose_name="prodotto")
    categoria = models.ForeignKey("prodotti.Categoria", on_delete=models.CASCADE, null=True, blank=True, related_name="+", verbose_name="categoria")
    percentuale = models.DecimalField("provvigione (%)", max_digits=5, decimal_places=2)

    class Meta:
        verbose_name = "regola provvigionale"
        verbose_name_plural = "regole provvigionali"

    def clean(self):
        if not self.prodotto_id and not self.categoria_id:
            raise ValidationError("Indica un prodotto o una categoria.")


class Provvigione(AziendaMixin):
    MATURATA, LIQUIDATA, ANNULLATA = "maturata", "liquidata", "annullata"
    STATI = [(MATURATA, "Maturata"), (LIQUIDATA, "Liquidata"), (ANNULLATA, "Annullata")]
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="provvigioni", verbose_name="commerciale")
    piano = models.ForeignKey(PianoProvvigioni, on_delete=models.SET_NULL, null=True, blank=True, related_name="provvigioni", verbose_name="piano")
    ordine = models.ForeignKey("vendite.OrdineVendita", on_delete=models.CASCADE, related_name="provvigioni", verbose_name="ordine")
    data = models.DateField("maturata il", default=timezone.localdate)
    base = models.DecimalField("venduto (imponibile)", max_digits=14, decimal_places=2, default=0)
    importo = models.DecimalField("provvigione", max_digits=14, decimal_places=2, default=0)
    descrizione = models.CharField("descrizione", max_length=200, blank=True)
    incasso_id = models.PositiveBigIntegerField("incasso", null=True, blank=True, editable=False, db_index=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=MATURATA)
    liquidata_il = models.DateField("liquidata il", null=True, blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "provvigione"
        verbose_name_plural = "provvigioni"
        ordering = ["-data", "-pk"]

    def __str__(self):
        return f"{self.ordine} · {self.utente} · {self.importo} €"
