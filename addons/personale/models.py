from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin

from . import calendario_lavoro


class Reparto(AziendaMixin):
    nome = models.CharField("nome", max_length=80)
    responsabile = models.ForeignKey("Dipendente", on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="reparti_guidati", verbose_name="responsabile")

    class Meta(AziendaMixin.Meta):
        verbose_name = "reparto"
        verbose_name_plural = "reparti"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Dipendente(AziendaMixin, ProprietaMixin):
    CONTRATTI = [("indeterminato", "Tempo indeterminato"), ("determinato", "Tempo determinato"),
                 ("apprendistato", "Apprendistato"), ("collaborazione", "Collaborazione"), ("stage", "Stage")]
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="dipendente", verbose_name="utente",
                                  help_text="per chiedere ferie e permessi da sé")
    nome = models.CharField("nome", max_length=80)
    cognome = models.CharField("cognome", max_length=80)
    codice_fiscale = models.CharField("codice fiscale", max_length=16, blank=True)
    email = models.EmailField("email", blank=True)
    telefono = models.CharField("telefono", max_length=40, blank=True)
    reparto = models.ForeignKey(Reparto, on_delete=models.SET_NULL, null=True, blank=True, related_name="dipendenti",
                                verbose_name="reparto")
    ruolo = models.CharField("ruolo", max_length=100, blank=True)
    responsabile = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="collaboratori", verbose_name="responsabile",
                                     help_text="approva le sue richieste")
    tipo_contratto = models.CharField("contratto", max_length=15, choices=CONTRATTI, default="indeterminato")
    data_assunzione = models.DateField("assunto il", default=timezone.localdate)
    data_cessazione = models.DateField("cessato il", null=True, blank=True)
    ore_settimanali = models.DecimalField("ore settimanali", max_digits=4, decimal_places=1, default=Decimal(40))
    giorni_ferie_annui = models.DecimalField("ferie annue (giorni)", max_digits=5, decimal_places=2,
                                             default=Decimal(26))
    ore_permesso_annue = models.DecimalField("permessi annui (ore)", max_digits=6, decimal_places=2,
                                             default=Decimal(72))
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "dipendente"
        verbose_name_plural = "dipendenti"
        ordering = ["cognome", "nome"]
        permissions = [("vedi_tutte_assenze", "Vede e approva le assenze di tutti")]

    def __str__(self):
        return f"{self.cognome} {self.nome}"

    @property
    def ore_al_giorno(self):
        return (self.ore_settimanali / 5) if self.ore_settimanali else Decimal(8)

    def approvatori(self):
        """Gli utenti che approvano le sue richieste: il responsabile (o quello del reparto)."""
        capo = self.responsabile or (self.reparto.responsabile if self.reparto_id else None)
        return [capo.utente] if capo is not None and capo.utente_id and capo.pk != self.pk else []


class TipoAssenza(models.Model):
    UNITA = [("giorni", "Giorni"), ("ore", "Ore")]
    SALDI = [("", "Non scala"), ("ferie", "Scala dalle ferie"), ("permessi", "Scala dai permessi")]
    nome = models.CharField("nome", max_length=80, unique=True)
    unita = models.CharField("si chiede a", max_length=6, choices=UNITA, default="giorni")
    saldo = models.CharField("saldo", max_length=10, choices=SALDI, blank=True)
    colore = models.CharField("colore", max_length=7, default="#1e3a8a")
    ordine = models.PositiveSmallIntegerField("ordine", default=10)
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "tipo di assenza"
        verbose_name_plural = "tipi di assenza"
        ordering = ["ordine", "nome"]

    def __str__(self):
        return self.nome


class Assenza(AziendaMixin):
    RICHIESTA, APPROVATA, RIFIUTATA, ANNULLATA = "richiesta", "approvata", "rifiutata", "annullata"
    STATI = [(RICHIESTA, "Da approvare"), (APPROVATA, "Approvata"), (RIFIUTATA, "Rifiutata"), (ANNULLATA, "Annullata")]
    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name="assenze",
                                   verbose_name="dipendente")
    tipo = models.ForeignKey(TipoAssenza, on_delete=models.PROTECT, verbose_name="tipo")
    dal = models.DateField("dal")
    al = models.DateField("al")
    ore = models.DecimalField("ore", max_digits=5, decimal_places=2, null=True, blank=True,
                              help_text="solo per i permessi a ore")
    motivo = models.CharField("motivo", max_length=250, blank=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=RICHIESTA, editable=False)
    decisa_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="decisa da", editable=False)
    decisa_il = models.DateTimeField("decisa il", null=True, blank=True, editable=False)
    nota_decisione = models.CharField("nota", max_length=250, blank=True, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "assenza"
        verbose_name_plural = "assenze"
        ordering = ["-dal", "-pk"]

    def __str__(self):
        periodo = f"{self.dal:%d/%m/%Y}" if self.dal == self.al else f"{self.dal:%d/%m} – {self.al:%d/%m/%Y}"
        return f"{self.tipo} di {self.dipendente} · {periodo}"

    @property
    def quantita(self):
        """Giorni lavorativi (o ore) che l'assenza vale."""
        if self.tipo_id and self.tipo.unita == "ore":
            return self.ore or Decimal(0)
        return Decimal(calendario_lavoro.giorni_lavorativi(self.dal, self.al))

    def clean(self):
        errori = {}
        if self.dal and self.al and self.al < self.dal:
            errori["al"] = "La fine viene prima dell'inizio."
        if self.tipo_id and self.tipo.unita == "ore":
            if not self.ore or self.ore <= 0:
                errori["ore"] = "Indica quante ore."
            elif self.dal and self.al and self.dal != self.al:
                errori["al"] = "Un permesso a ore vale per un giorno solo."
        if self.dal and self.al and not errori and self.tipo_id and self.tipo.unita == "giorni" \
                and calendario_lavoro.giorni_lavorativi(self.dal, self.al) == 0:
            errori["dal"] = "Nel periodo non ci sono giorni lavorativi."
        if self.dipendente_id and self.dal and self.al and not errori:
            sovrapposte = (Assenza.objects.filter(dipendente_id=self.dipendente_id, dal__lte=self.al, al__gte=self.dal)
                           .exclude(stato__in=[self.RIFIUTATA, self.ANNULLATA]).exclude(pk=self.pk))
            if self.tipo_id and self.tipo.unita == "giorni" and sovrapposte.filter(tipo__unita="giorni").exists():
                errori["dal"] = "C'è già un'assenza in questo periodo."
        if errori:
            raise ValidationError(errori)
