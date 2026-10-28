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
