from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin
from core.storage import StoragePrivato

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


class Posizione(AziendaMixin):
    """Un ruolo dell'organico (es. «Commerciale senior»): in quale reparto e quante persone servono."""
    nome = models.CharField("nome", max_length=100)
    reparto = models.ForeignKey(Reparto, on_delete=models.SET_NULL, null=True, blank=True, related_name="posizioni",
                                verbose_name="reparto")
    organico = models.PositiveSmallIntegerField("organico previsto", default=1,
                                                help_text="quante persone servono in questa posizione")
    descrizione = models.TextField("descrizione", blank=True, help_text="compiti e requisiti")
    attiva = models.BooleanField("attiva", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "posizione"
        verbose_name_plural = "posizioni"
        ordering = ["reparto__nome", "nome"]

    def __str__(self):
        return self.nome

    def occupati(self):
        return self.dipendenti.filter(attivo=True).count()


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
    posizione = models.ForeignKey(Posizione, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="dipendenti", verbose_name="posizione")
    ruolo = models.CharField("ruolo", max_length=100, blank=True, help_text="se vuoto, il nome della posizione")
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
    badge = models.CharField("badge", max_length=40, blank=True, help_text="il codice letto dal lettore del chiosco")
    pin_impronta = models.CharField("PIN", max_length=64, blank=True, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "dipendente"
        verbose_name_plural = "dipendenti"
        ordering = ["cognome", "nome"]
        permissions = [("vedi_tutte_assenze", "Vede e approva le assenze di tutti")]

    def __str__(self):
        return f"{self.cognome} {self.nome}"

    def clean(self):
        super().clean()
        capo, visti = self.responsabile, {self.pk}
        while capo is not None and self.pk:                     # niente giri nella catena dei responsabili
            if capo.pk in visti:
                raise ValidationError({"responsabile": "Così la catena dei responsabili gira in tondo."})
            visti.add(capo.pk)
            capo = capo.responsabile

    def save(self, *args, **kwargs):
        if not self.ruolo and self.posizione_id:
            self.ruolo = self.posizione.nome[:100]
        super().save(*args, **kwargs)

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


class Timbratura(AziendaMixin):
    """Un'entrata o un'uscita: dal chiosco, dal web o corretta a mano da un responsabile."""
    ENTRATA, USCITA = "entrata", "uscita"
    VERSI = [(ENTRATA, "Entrata"), (USCITA, "Uscita")]
    FONTI = [("chiosco", "Chiosco"), ("web", "Web o telefono"), ("manuale", "Inserita a mano")]
    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name="timbrature", verbose_name="dipendente")
    verso = models.CharField("verso", max_length=8, choices=VERSI)
    il = models.DateTimeField("il", default=timezone.now)
    fonte = models.CharField("da", max_length=8, choices=FONTI, default="chiosco")
    nota = models.CharField("nota", max_length=200, blank=True, help_text="obbligatoria se inserita a mano")
    inserita_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="inserita da")

    class Meta(AziendaMixin.Meta):
        verbose_name = "timbratura"
        verbose_name_plural = "timbrature"
        ordering = ["-il"]
        indexes = [models.Index(fields=["dipendente", "il"])]

    def __str__(self):
        return f"{self.dipendente} · {self.get_verso_display()} {timezone.localtime(self.il):%d/%m %H:%M}"


class ContrattoLavoro(AziendaMixin):
    """Il contratto di un dipendente in un periodo: tipo, CCNL e livello, orario, ferie e permessi annui, retribuzione.
    Quello in vigore aggiorna i dati del dipendente su cui contano saldi e presenze. Dati riservati alle Risorse umane."""
    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name="contratti", verbose_name="dipendente")
    tipo = models.CharField("tipo", max_length=15, choices=Dipendente.CONTRATTI, default="indeterminato")
    ccnl = models.CharField("CCNL", max_length=120, blank=True, help_text="es. Commercio e terziario")
    livello = models.CharField("livello", max_length=30, blank=True)
    mansione = models.CharField("mansione", max_length=120, blank=True)
    dal = models.DateField("dal")
    al = models.DateField("al", null=True, blank=True, help_text="vuoto = a tempo indeterminato")
    ore_settimanali = models.DecimalField("ore settimanali", max_digits=4, decimal_places=1, default=Decimal(40))
    giorni_ferie_annui = models.DecimalField("ferie annue (giorni)", max_digits=5, decimal_places=2, default=Decimal(26))
    ore_permesso_annue = models.DecimalField("permessi annui (ore)", max_digits=6, decimal_places=2, default=Decimal(32))
    retribuzione_annua = models.DecimalField("retribuzione lorda annua (€)", max_digits=12, decimal_places=2, null=True, blank=True)
    mensilita = models.PositiveSmallIntegerField("mensilità", default=13)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "contratto di lavoro"
        verbose_name_plural = "contratti di lavoro"
        ordering = ["-dal", "-pk"]

    def __str__(self):
        return f"{self.dipendente} · {self.get_tipo_display()} dal {self.dal:%d/%m/%Y}"

    def clean(self):
        if self.dal and self.al and self.al < self.dal:
            raise ValidationError({"al": "La fine viene dopo l'inizio."})
        if self.tipo == "determinato" and not self.al:
            raise ValidationError({"al": "Un contratto a tempo determinato ha una scadenza."})
        if self.dipendente_id and self.dal:
            sovrapposti = ContrattoLavoro.objects.filter(dipendente_id=self.dipendente_id).exclude(pk=self.pk).filter(
                models.Q(al__isnull=True) | models.Q(al__gte=self.dal))
            if self.al:
                sovrapposti = sovrapposti.filter(dal__lte=self.al)
            if sovrapposti.exists():
                raise ValidationError("Il periodo si sovrappone a un altro contratto: chiudi prima quello (indica la sua fine).")

    @property
    def mensile(self):
        return (self.retribuzione_annua / self.mensilita).quantize(Decimal("0.01")) if self.retribuzione_annua and self.mensilita else None


class VoceRetributiva(models.Model):
    """Una voce della busta paga prevista dal contratto: superminimo, indennità, buoni pasto…"""
    FISSA, VARIABILE = "fissa", "variabile"
    contratto = models.ForeignKey(ContrattoLavoro, on_delete=models.CASCADE, related_name="voci", verbose_name="contratto")
    nome = models.CharField("voce", max_length=100)
    importo = models.DecimalField("importo mensile (€)", max_digits=10, decimal_places=2)
    tipo = models.CharField("tipo", max_length=10, choices=[(FISSA, "Fissa"), (VARIABILE, "Variabile")], default=FISSA)

    class Meta:
        verbose_name = "voce retributiva"
        verbose_name_plural = "voci retributive"
        ordering = ["pk"]


def _percorso_documento(instance, filename):
    import uuid
    return f"personale/{timezone.now():%Y/%m}/{uuid.uuid4().hex}-{filename}"


class DocumentoDipendente(AziendaMixin):
    """Un documento riservato per il dipendente (cedolino, CU, contratto firmato…): lo carica l'ufficio del personale,
    lo vede solo lui nel suo profilo."""
    TIPI = [("cedolino", "Cedolino"), ("cu", "Certificazione Unica"), ("contratto", "Contratto"), ("comunicazione", "Comunicazione"),
            ("altro", "Altro")]
    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name="documenti", verbose_name="dipendente")
    tipo = models.CharField("tipo", max_length=14, choices=TIPI, default="cedolino")
    titolo = models.CharField("titolo", max_length=150, help_text="es. Cedolino ottobre 2026")
    periodo = models.DateField("periodo", null=True, blank=True, help_text="il mese a cui si riferisce")
    file = models.FileField("file", upload_to=_percorso_documento, storage=StoragePrivato(), max_length=300)
    pubblicato_il = models.DateTimeField("pubblicato il", auto_now_add=True)
    letto_il = models.DateTimeField("letto il", null=True, blank=True, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "documento del dipendente"
        verbose_name_plural = "documenti dei dipendenti"
        ordering = ["-periodo", "-pubblicato_il"]

    def __str__(self):
        return f"{self.titolo} · {self.dipendente}"


class RichiestaModifica(AziendaMixin):
    """Il dipendente chiede di correggere i suoi dati: l'ufficio del personale approva (e i campi si aggiornano) o rifiuta."""
    IN_ATTESA, APPROVATA, RIFIUTATA = "in_attesa", "approvata", "rifiutata"
    STATI = [(IN_ATTESA, "In attesa"), (APPROVATA, "Approvata"), (RIFIUTATA, "Rifiutata")]
    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name="richieste_modifica", verbose_name="dipendente")
    email = models.EmailField("nuova email", blank=True)
    telefono = models.CharField("nuovo telefono", max_length=40, blank=True)
    altro = models.TextField("altro da cambiare", blank=True, help_text="es. indirizzo, IBAN per gli accrediti")
    stato = models.CharField("stato", max_length=10, choices=STATI, default=IN_ATTESA, editable=False)
    decisa_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                  verbose_name="decisa da", editable=False)
    decisa_il = models.DateTimeField("decisa il", null=True, blank=True, editable=False)
    creata = models.DateTimeField("chiesta il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "richiesta di modifica dei dati"
        verbose_name_plural = "richieste di modifica dei dati"
        ordering = ["-creata"]

    def __str__(self):
        return f"Modifica dati di {self.dipendente} del {self.creata:%d/%m/%Y}"

    def clean(self):
        if not (self.email or self.telefono or self.altro.strip()):
            raise ValidationError("Scrivi che cosa va cambiato.")


class TurnoLavoro(AziendaMixin):
    nome = models.CharField("nome", max_length=60, help_text="es. Mattina, Pomeriggio, Notte")
    inizio = models.TimeField("dalle")
    fine = models.TimeField("alle")
    pausa_minuti = models.PositiveSmallIntegerField("pausa (minuti)", default=0)
    colore = models.CharField("colore", max_length=7, default="#2563eb")
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "turno"
        verbose_name_plural = "turni"
        ordering = ["inizio", "nome"]

    def __str__(self):
        return f"{self.nome} {self.inizio:%H:%M}–{self.fine:%H:%M}"

    @property
    def ore(self):
        import datetime as dt
        a = dt.datetime.combine(dt.date.today(), self.inizio)
        b = dt.datetime.combine(dt.date.today(), self.fine)
        if b <= a:
            b += dt.timedelta(days=1)                 # turno che passa la mezzanotte
        return Decimal((b - a).seconds - self.pausa_minuti * 60) / 3600


class AssegnazioneTurno(AziendaMixin):
    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name="turni", verbose_name="dipendente")
    data = models.DateField("giorno")
    turno = models.ForeignKey(TurnoLavoro, on_delete=models.PROTECT, related_name="assegnazioni", verbose_name="turno")
    nota = models.CharField("nota", max_length=120, blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "turno assegnato"
        verbose_name_plural = "turni assegnati"
        ordering = ["data", "turno__inizio"]
        constraints = [models.UniqueConstraint(fields=["dipendente", "data"], name="personale_un_turno_al_giorno")]
