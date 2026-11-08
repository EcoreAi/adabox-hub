"""Consensi per finalità, richieste degli interessati, anonimizzazioni fatte e tempi di conservazione."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin


class Finalita(models.Model):
    """Per che cosa si usano i dati (es. «Newsletter»): ogni consenso è per una finalità."""
    BASI = [("consenso", "Consenso"), ("contratto", "Esecuzione di un contratto"), ("obbligo", "Obbligo di legge"),
            ("interesse", "Legittimo interesse")]
    nome = models.CharField("nome", max_length=100, unique=True)
    descrizione = models.TextField("descrizione", blank=True, help_text="come la legge chi dà il consenso")
    base_giuridica = models.CharField("base giuridica", max_length=10, choices=BASI, default="consenso")
    attiva = models.BooleanField("attiva", default=True)

    class Meta:
        verbose_name = "finalità"
        verbose_name_plural = "finalità"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Consenso(AziendaMixin):
    """Una registrazione: dato o revocato, quando, come e da chi. Lo stato di oggi è l'ultima per finalità; le
    precedenti restano come prova."""
    FONTI = [("modulo", "Modulo web"), ("email", "Email"), ("telefono", "Telefono"), ("persona", "Di persona"),
             ("portale", "Portale clienti"), ("contratto", "Contratto firmato"), ("importazione", "Importazione")]
    contatto = models.ForeignKey("contatti.Contatto", on_delete=models.CASCADE, related_name="consensi", verbose_name="contatto")
    finalita = models.ForeignKey(Finalita, on_delete=models.PROTECT, related_name="consensi", verbose_name="finalità")
    dato = models.BooleanField("consenso dato", default=True, help_text="spento = revocato o negato")
    il = models.DateTimeField("il", default=timezone.now)
    fonte = models.CharField("come", max_length=12, choices=FONTI, default="persona")
    note = models.CharField("note", max_length=250, blank=True, help_text="es. testo dell'informativa accettata, riferimento della email")
    registrato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+", verbose_name="registrato da")

    class Meta(AziendaMixin.Meta):
        verbose_name = "consenso"
        verbose_name_plural = "consensi"
        ordering = ["-il", "-pk"]
        permissions = [("esporta_dati", "Esporta i dati di un contatto"), ("anonimizza_contatto", "Anonimizza un contatto")]

    def __str__(self):
        return f"{self.contatto} · {self.finalita}: {'dato' if self.dato else 'revocato'}"


class RichiestaInteressato(AziendaMixin):
    """Una richiesta di un interessato (accesso, cancellazione…): va evasa entro 30 giorni."""
    TIPI = [("accesso", "Accesso ai dati"), ("portabilita", "Portabilità (esportazione)"), ("rettifica", "Rettifica"),
            ("cancellazione", "Cancellazione"), ("limitazione", "Limitazione"), ("opposizione", "Opposizione")]
    contatto = models.ForeignKey("contatti.Contatto", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="richieste_privacy", verbose_name="contatto")
    richiedente = models.CharField("chi la fa", max_length=200, help_text="nome ed email o recapito")
    tipo = models.CharField("tipo", max_length=14, choices=TIPI)
    ricevuta_il = models.DateField("ricevuta il", default=timezone.localdate)
    scadenza = models.DateField("da evadere entro", null=True, blank=True, editable=False)
    evasa_il = models.DateField("evasa il", null=True, blank=True)
    esito = models.TextField("esito", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "richiesta di un interessato"
        verbose_name_plural = "richieste degli interessati"
        ordering = ["evasa_il", "scadenza", "-pk"]

    def __str__(self):
        return f"{self.get_tipo_display()} · {self.richiedente}"

    def save(self, *args, **kwargs):
        import datetime
        self.scadenza = self.ricevuta_il + datetime.timedelta(days=30) if self.ricevuta_il else None
        super().save(*args, **kwargs)


class Anonimizzazione(models.Model):
    """Un contatto anonimizzato: quando, da chi e se in parte (restano i dati che servono ai documenti fiscali)."""
    contatto = models.OneToOneField("contatti.Contatto", on_delete=models.CASCADE, related_name="anonimizzazione",
                                    verbose_name="contatto")
    il = models.DateTimeField("il", auto_now_add=True)
    da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                           verbose_name="da")
    parziale = models.BooleanField("parziale", default=False, help_text="restano i dati dei documenti da conservare per legge")
    dettagli = models.JSONField("che cosa è stato tolto", default=list, blank=True)

    class Meta:
        verbose_name = "anonimizzazione"
        verbose_name_plural = "anonimizzazioni"

    def __str__(self):
        return f"{self.contatto} · {self.il:%d/%m/%Y}"


class RegolaConservazione(models.Model):
    """Per quanto si tengono i dati di un tipo dichiarato dai moduli (privacy.conservazione): poi il cron li cancella."""
    chiave = models.CharField("dati", max_length=80, unique=True)
    giorni = models.PositiveIntegerField("giorni", help_text="dopo, i record si cancellano")
    attiva = models.BooleanField("attiva", default=True)
    ultima_esecuzione = models.DateTimeField("ultima esecuzione", null=True, blank=True, editable=False)
    cancellati = models.PositiveIntegerField("cancellati l'ultima volta", default=0, editable=False)

    class Meta:
        verbose_name = "regola di conservazione"
        verbose_name_plural = "regole di conservazione"
        ordering = ["chiave"]

    def __str__(self):
        from .conservazione import etichetta
        return f"{etichetta(self.chiave)}: {self.giorni} giorni"
