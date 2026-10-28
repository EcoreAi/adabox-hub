import uuid

from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin
from core.storage import StoragePrivato


def _percorso(instance, filename):
    return f"sdi/{timezone.now():%Y/%m}/{uuid.uuid4().hex}-{filename}"


class Trasmissione(AziendaMixin):
    """Un invio di una fattura allo SDI (dopo uno scarto se ne fa un altro, con un nuovo progressivo)."""
    PRONTA, INVIATA, CONSEGNATA, MANCATA_CONSEGNA, SCARTATA = "pronta", "inviata", "consegnata", "mancata", "scartata"
    ACCETTATA, RIFIUTATA, DECORSA, ERRORE = "accettata", "rifiutata", "decorsa", "errore"
    STATI = [(PRONTA, "Pronta da caricare"), (INVIATA, "Inviata, in attesa"), (CONSEGNATA, "Consegnata"),
             (MANCATA_CONSEGNA, "Non recapitata (disponibile nel cassetto fiscale)"), (SCARTATA, "Scartata"),
             (ACCETTATA, "Accettata dalla PA"), (RIFIUTATA, "Rifiutata dalla PA"),
             (DECORSA, "Decorrenza termini"), (ERRORE, "Errore di invio")]
    CONCLUSI = {CONSEGNATA, MANCATA_CONSEGNA, ACCETTATA, DECORSA}
    fattura = models.ForeignKey("fatturazione.Fattura", on_delete=models.PROTECT, related_name="trasmissioni",
                                verbose_name="fattura")
    nome_file = models.CharField("file", max_length=60, db_index=True)
    file = models.FileField("XML", upload_to=_percorso, storage=StoragePrivato(), max_length=300)
    canale = models.CharField("canale", max_length=10)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=PRONTA)
    identificativo_sdi = models.CharField("identificativo SDI", max_length=20, blank=True, db_index=True)
    creata = models.DateTimeField("creata il", auto_now_add=True)
    inviata_il = models.DateTimeField("inviata il", null=True, blank=True)
    esito_il = models.DateTimeField("esito il", null=True, blank=True)
    errori = models.JSONField("errori", default=list, blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "trasmissione"
        verbose_name_plural = "trasmissioni"
        ordering = ["-creata", "-pk"]

    def __str__(self):
        return self.nome_file


class NotificaSdi(models.Model):
    """Un file ricevuto dallo SDI: ricevuta di consegna, scarto, mancata consegna, esito, decorrenza termini..."""
    TIPI = [("RC", "Ricevuta di consegna"), ("NS", "Notifica di scarto"), ("MC", "Mancata consegna"),
            ("NE", "Esito del committente"), ("DT", "Decorrenza termini"), ("AT", "Attestazione di trasmissione"),
            ("EC", "Esito inviato"), ("SE", "Scarto dell'esito"), ("MT", "Metadati")]
    trasmissione = models.ForeignKey(Trasmissione, on_delete=models.CASCADE, null=True, blank=True,
                                     related_name="notifiche", verbose_name="trasmissione")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, null=True, blank=True)
    tipo = models.CharField("tipo", max_length=2, choices=TIPI)
    nome_file = models.CharField("file", max_length=80)
    file = models.FileField("XML", upload_to=_percorso, storage=StoragePrivato(), max_length=300)
    identificativo_sdi = models.CharField("identificativo SDI", max_length=20, blank=True)
    file_fattura = models.CharField("file della fattura", max_length=60, blank=True)
    ricevuta_il = models.DateTimeField("ricevuta il", auto_now_add=True)
    dati = models.JSONField("contenuto", default=dict, blank=True)

    class Meta:
        verbose_name = "notifica SDI"
        verbose_name_plural = "notifiche SDI"
        ordering = ["-ricevuta_il", "-pk"]
        constraints = [models.UniqueConstraint(fields=["nome_file"], name="sdi_notifica_unica")]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.file_fattura or self.nome_file}"


class FatturaPassiva(AziendaMixin):
    """Fattura ricevuta da un fornitore tramite lo SDI (o caricata a mano), letta dal suo XML."""
    DA_VERIFICARE, REGISTRATA, CONTESTATA = "da_verificare", "registrata", "contestata"
    STATI = [(DA_VERIFICARE, "Da verificare"), (REGISTRATA, "Registrata"), (CONTESTATA, "Contestata")]
    fornitore = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="fatture_passive",
                                  verbose_name="fornitore")
    tipo_documento = models.CharField("tipo", max_length=4, default="TD01")
    numero = models.CharField("numero", max_length=20)
    data = models.DateField("data")
    causale = models.TextField("causale", blank=True)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2, default=0)
    imposta = models.DecimalField("IVA", max_digits=14, decimal_places=2, default=0)
    totale = models.DecimalField("totale", max_digits=14, decimal_places=2, default=0)
    stato = models.CharField("stato", max_length=15, choices=STATI, default=DA_VERIFICARE)
    pagata = models.BooleanField("pagata", default=False)
    nome_file = models.CharField("file", max_length=80)
    originale = models.FileField("file ricevuto", upload_to=_percorso, storage=StoragePrivato(), max_length=300)
    identificativo_sdi = models.CharField("identificativo SDI", max_length=20, blank=True)
    ricevuta_il = models.DateTimeField("ricevuta il", auto_now_add=True)
    registrata_il = models.DateField("registrata il", null=True, blank=True)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "fattura ricevuta"
        verbose_name_plural = "fatture ricevute"
        ordering = ["-data", "-pk"]
        constraints = [models.UniqueConstraint(fields=["azienda", "fornitore", "numero", "data"],
                                               name="sdi_passiva_unica")]

    def __str__(self):
        return f"{self.numero} del {self.data:%d/%m/%Y} · {self.fornitore}"

    @property
    def nota_credito(self):
        return self.tipo_documento == "TD04"


class RigaPassiva(models.Model):
    fattura = models.ForeignKey(FatturaPassiva, on_delete=models.CASCADE, related_name="righe")
    numero_linea = models.PositiveIntegerField("n.", default=1)
    descrizione = models.TextField("descrizione")
    quantita = models.DecimalField("quantità", max_digits=21, decimal_places=8, null=True, blank=True)
    unita = models.CharField("unità", max_length=10, blank=True)
    prezzo = models.DecimalField("prezzo", max_digits=21, decimal_places=8, default=0)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2, default=0)
    aliquota = models.DecimalField("IVA %", max_digits=5, decimal_places=2, default=0)
    natura = models.CharField("natura", max_length=4, blank=True)

    class Meta:
        verbose_name = "riga"
        verbose_name_plural = "righe"
        ordering = ["numero_linea", "pk"]


class RiepilogoPassiva(models.Model):
    fattura = models.ForeignKey(FatturaPassiva, on_delete=models.CASCADE, related_name="riepilogo")
    aliquota = models.DecimalField("IVA %", max_digits=5, decimal_places=2)
    natura = models.CharField("natura", max_length=4, blank=True)
    imponibile = models.DecimalField("imponibile", max_digits=14, decimal_places=2)
    imposta = models.DecimalField("imposta", max_digits=14, decimal_places=2)
    esigibilita = models.CharField("esigibilità", max_length=1, blank=True)

    class Meta:
        verbose_name = "riepilogo IVA"
        verbose_name_plural = "riepilogo IVA"
        ordering = ["pk"]


class ScadenzaPassiva(models.Model):
    fattura = models.ForeignKey(FatturaPassiva, on_delete=models.CASCADE, related_name="scadenze",
                                verbose_name="fattura")
    data = models.DateField("scadenza", null=True, blank=True)
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2)
    modalita = models.CharField("modalità", max_length=4, blank=True)
    iban = models.CharField("IBAN", max_length=34, blank=True)
    pagata = models.BooleanField("pagata", default=False)
    pagata_il = models.DateField("pagata il", null=True, blank=True)

    class Meta:
        verbose_name = "scadenza da pagare"
        verbose_name_plural = "scadenze da pagare"
        ordering = ["pagata", "data", "pk"]

    def __str__(self):
        return f"{self.fattura} · {self.importo} €"
