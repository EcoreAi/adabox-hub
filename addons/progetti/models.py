from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q, Sum
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin


class FaseCompito(models.Model):
    nome = models.CharField("nome", max_length=60)
    ordine = models.PositiveSmallIntegerField("ordine", default=10)
    chiusa = models.BooleanField("compito completato", default=False)

    class Meta:
        verbose_name = "fase"
        verbose_name_plural = "fasi"
        ordering = ["ordine", "pk"]

    def __str__(self):
        return self.nome


class TipoCompito(models.Model):
    nome = models.CharField("nome", max_length=60)
    colore = models.CharField("colore", max_length=7, default="#8e8e93", help_text="es. #ff3b30")
    ordine = models.PositiveSmallIntegerField("ordine", default=10)
    difetto = models.BooleanField("è un difetto", default=False,
                                  help_text="i compiti di questo tipo sono bug (difetti trovati dal collaudo o dai clienti)")

    class Meta:
        verbose_name = "tipo di lavoro"
        verbose_name_plural = "tipi di lavoro"
        ordering = ["ordine", "pk"]

    def __str__(self):
        return self.nome


def fase_iniziale():
    return FaseCompito.objects.order_by("ordine", "pk").values_list("pk", flat=True).first()


class Progetto(AziendaMixin, ProprietaMixin):
    ATTIVO, SOSPESO, CHIUSO = "attivo", "sospeso", "chiuso"
    STATI = [(ATTIVO, "Attivo"), (SOSPESO, "Sospeso"), (CHIUSO, "Chiuso")]
    codice = models.CharField("codice", max_length=20, blank=True, editable=False, db_index=True)
    nome = models.CharField("nome", max_length=200)
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="progetti", verbose_name="cliente")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="progetti_responsabile", verbose_name="responsabile")
    membri = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="progetti",
                                    verbose_name="membri")
    inizio = models.DateField("inizio", null=True, blank=True)
    fine = models.DateField("fine prevista", null=True, blank=True)
    stato = models.CharField("stato", max_length=8, choices=STATI, default=ATTIVO)
    descrizione = models.TextField("descrizione", blank=True)
    budget_ore = models.DecimalField("budget di ore", max_digits=9, decimal_places=2, default=0, blank=True,
                                     help_text="vuoto o 0 = senza budget")
    budget_avvisato = models.PositiveSmallIntegerField("avviso di budget mandato al", default=0, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "progetto"
        verbose_name_plural = "progetti"
        ordering = ["nome"]
        permissions = [("vedi_tutti_progetti", "Può vedere tutti i progetti, anche senza esserne membro")]

    def __str__(self):
        return self.nome

    def clean(self):
        if self.inizio and self.fine and self.fine < self.inizio:
            raise ValidationError({"fine": "La fine prevista non può precedere l'inizio."})

    def save(self, *args, **kwargs):
        if self.budget_ore is None:
            self.budget_ore = 0
        super().save(*args, **kwargs)

    def riepilogo_compiti(self):
        """(totale, completati, percentuale, [(fase, numero)])."""
        per_fase = list(FaseCompito.objects.annotate(n=Count("compiti", filter=Q(compiti__progetto=self))))
        totale = sum(f.n for f in per_fase)
        completati = sum(f.n for f in per_fase if f.chiusa)
        return totale, completati, round(100 * completati / totale) if totale else 0, [(f, f.n) for f in per_fase]

    def ore_previste(self):
        return self.compiti.aggregate(t=Sum("ore_previste"))["t"] or 0

    def ore_consumate(self):
        """Ore registrate nel timesheet (0 se il timesheet non è installato)."""
        from django.apps import apps
        if not apps.is_installed("timesheet"):
            return 0
        return apps.get_model("timesheet", "RigaOre").objects.filter(progetto=self).aggregate(t=Sum("ore"))["t"] or 0

    def budget(self):
        """(budget, consumate, percentuale) o None senza budget."""
        if not self.budget_ore:
            return None
        consumate = self.ore_consumate()
        return self.budget_ore, consumate, round(100 * consumate / self.budget_ore)


class Milestone(AziendaMixin):
    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="milestone", verbose_name="progetto")
    nome = models.CharField("nome", max_length=200)
    scadenza = models.DateField("scadenza", null=True, blank=True)
    descrizione = models.TextField("descrizione", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "milestone"
        verbose_name_plural = "milestone"
        ordering = ["scadenza", "pk"]

    def __str__(self):
        return f"{self.nome} ({self.progetto})"

    def avanzamento(self):
        """(totale, completati, percentuale)."""
        totale = self.compiti.count()
        fatti = self.compiti.filter(fase__chiusa=True).count()
        return totale, fatti, round(100 * fatti / totale) if totale else 0

    def raggiunta(self):
        totale, fatti, _ = self.avanzamento()
        return bool(totale) and totale == fatti


class Sprint(AziendaMixin):
    PIANIFICATO, ATTIVO, CHIUSO = "pianificato", "attivo", "chiuso"
    STATI = [(PIANIFICATO, "Pianificato"), (ATTIVO, "In corso"), (CHIUSO, "Chiuso")]
    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="sprint", verbose_name="progetto")
    nome = models.CharField("nome", max_length=100)
    inizio = models.DateField("inizio")
    fine = models.DateField("fine")
    obiettivo = models.TextField("obiettivo", blank=True)
    stato = models.CharField("stato", max_length=12, choices=STATI, default=PIANIFICATO)

    class Meta(AziendaMixin.Meta):
        verbose_name = "sprint"
        verbose_name_plural = "sprint"
        ordering = ["inizio", "pk"]

    def __str__(self):
        return f"{self.nome} ({self.progetto})"

    def clean(self):
        if self.inizio and self.fine and self.fine < self.inizio:
            raise ValidationError({"fine": "La fine non può precedere l'inizio."})

    def punti(self):
        """(totali, completati): i compiti senza stima contano 1 punto."""
        totali = fatti = 0
        for punti, chiusa in self.compiti.values_list("punti", "fase__chiusa"):
            totali += punti or 1
            fatti += (punti or 1) if chiusa else 0
        return totali, fatti

    def burndown(self, oggi=None):
        """[(giorno, punti rimasti)] dall'inizio alla fine (fino a oggi se in corso) e la retta ideale."""
        import datetime
        oggi = oggi or timezone.localdate()
        compiti = list(self.compiti.values_list("punti", "completato_il"))
        totale = sum(p or 1 for p, _ in compiti)
        giorni = (self.fine - self.inizio).days + 1
        reale, ideale = [], []
        for i in range(giorni):
            giorno = self.inizio + datetime.timedelta(days=i)
            ideale.append((giorno, totale - totale * i / max(giorni - 1, 1)))
            if giorno <= oggi:
                fatti = sum(p or 1 for p, c in compiti if c and timezone.localdate(c) <= giorno)
                reale.append((giorno, totale - fatti))
        return reale, ideale

    def successivo(self):
        return (Sprint.objects.filter(progetto=self.progetto, stato=Sprint.PIANIFICATO, inizio__gte=self.inizio)
                .exclude(pk=self.pk).order_by("inizio", "pk").first())


class Rilascio(AziendaMixin):
    PIANIFICATO, RILASCIATO = "pianificato", "rilasciato"
    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="rilasci", verbose_name="progetto")
    versione = models.CharField("versione", max_length=40, help_text="es. 2.4.0")
    data_prevista = models.DateField("data prevista", null=True, blank=True)
    stato = models.CharField("stato", max_length=12, default=PIANIFICATO,
                             choices=[(PIANIFICATO, "Pianificato"), (RILASCIATO, "Rilasciato")])
    rilasciato_il = models.DateTimeField("rilasciato il", null=True, blank=True, editable=False)
    note = models.TextField("note di rilascio", blank=True,
                            help_text="vuote = generate dai compiti completati al rilascio")

    class Meta(AziendaMixin.Meta):
        verbose_name = "rilascio"
        verbose_name_plural = "rilasci"
        ordering = ["-data_prevista", "-pk"]
        constraints = [models.UniqueConstraint(fields=["progetto", "versione"], name="rilascio_versione_unica")]

    def __str__(self):
        return f"{self.progetto} {self.versione}"

    def note_generate(self):
        """Note di rilascio dai compiti completati, raggruppati per tipo di lavoro."""
        gruppi = {}
        for c in self.compiti.filter(fase__chiusa=True).select_related("tipo").order_by("tipo__ordine", "pk"):
            gruppi.setdefault(c.tipo.nome if c.tipo else "Altro", []).append(c.titolo)
        return "\n\n".join(f"{tipo}\n" + "\n".join(f"- {t}" for t in titoli) for tipo, titoli in gruppi.items())

    def rilascia(self, utente=None):
        """Pubblica il rilascio (una volta sola): note generate se vuote, segnale rilascio_pubblicato."""
        if self.stato == Rilascio.RILASCIATO:
            return False
        from .segnali import rilascio_pubblicato
        self.stato, self.rilasciato_il = Rilascio.RILASCIATO, timezone.now()
        self.note = self.note or self.note_generate()
        self.save(update_fields=["stato", "rilasciato_il", "note"])
        rilascio_pubblicato.send(sender=Rilascio, rilascio=self, utente=utente)
        return True


class Compito(AziendaMixin, ProprietaMixin):
    NORMALE, ALTA = "normale", "alta"
    progetto = models.ForeignKey(Progetto, on_delete=models.CASCADE, related_name="compiti", verbose_name="progetto")
    titolo = models.CharField("titolo", max_length=200)
    descrizione = models.TextField("descrizione", blank=True)
    fase = models.ForeignKey(FaseCompito, on_delete=models.PROTECT, default=fase_iniziale, related_name="compiti",
                             verbose_name="fase")
    assegnatari = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="compiti",
                                         verbose_name="assegnatari")
    scadenza = models.DateField("scadenza", null=True, blank=True)
    priorita = models.CharField("priorità", max_length=7, choices=[(NORMALE, "Normale"), (ALTA, "Alta")], default=NORMALE)
    ore_previste = models.DecimalField("ore previste", max_digits=7, decimal_places=2, default=0)
    padre = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="sottocompiti",
                              verbose_name="compito padre")
    tipo = models.ForeignKey(TipoCompito, on_delete=models.SET_NULL, null=True, blank=True, related_name="compiti",
                             verbose_name="tipo")
    punti = models.PositiveSmallIntegerField("punti (stima)", null=True, blank=True,
                                             help_text="stima relativa dell'impegno, es. 1, 2, 3, 5, 8")
    milestone = models.ForeignKey(Milestone, on_delete=models.SET_NULL, null=True, blank=True, related_name="compiti",
                                  verbose_name="milestone")
    sprint = models.ForeignKey(Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="compiti",
                               verbose_name="sprint")
    rilascio = models.ForeignKey(Rilascio, on_delete=models.SET_NULL, null=True, blank=True, related_name="compiti",
                                 verbose_name="rilascio")
    bloccato_da = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="blocca",
                                         verbose_name="bloccato da",
                                         help_text="compiti da completare prima di questo")
    completato_il = models.DateTimeField("completato il", null=True, blank=True, editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "compito"
        verbose_name_plural = "compiti"
        ordering = ["scadenza", "pk"]

    def __str__(self):
        return self.titolo

    def clean(self):
        if self.padre_id:
            if self.padre_id == self.pk:
                raise ValidationError({"padre": "Un compito non può essere il padre di se stesso."})
            if self.progetto_id and self.padre.progetto_id != self.progetto_id:
                raise ValidationError({"padre": "Il compito padre deve essere dello stesso progetto."})
        if self.progetto_id:
            errori = {campo: f"Scegli {etichetta} dello stesso progetto."
                      for campo, etichetta in (("milestone", "una milestone"), ("sprint", "uno sprint"),
                                               ("rilascio", "un rilascio"))
                      if getattr(self, f"{campo}_id") and getattr(self, campo).progetto_id != self.progetto_id}
            if errori:
                raise ValidationError(errori)

    def bloccanti_aperti(self):
        return list(self.bloccato_da.filter(fase__chiusa=False)) if self.pk else []

    def save(self, *args, **kwargs):
        """completato_il segue la fase: impostato entrando in una fase chiusa, tolto riaprendo."""
        chiusa = FaseCompito.objects.filter(pk=self.fase_id, chiusa=True).exists() if self.fase_id else False
        if chiusa != bool(self.completato_il):
            self.completato_il = timezone.now() if chiusa else None
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = {*kwargs["update_fields"], "completato_il"}
        super().save(*args, **kwargs)


def blocco(aperti):
    return "Prima vanno completati: " + ", ".join(f"«{c}»" for c in aperti) + "."


def crea_ciclo(compito, bloccanti):
    """True se far dipendere `compito` da `bloccanti` crea un ciclo (o un compito blocca se stesso)."""
    visti, da_vedere = set(), [b.pk for b in bloccanti]
    while da_vedere:
        pk = da_vedere.pop()
        if pk == compito.pk:
            return True
        if pk in visti:
            continue
        visti.add(pk)
        da_vedere.extend(Compito.bloccato_da.through.objects.filter(from_compito_id=pk)
                         .values_list("to_compito_id", flat=True))
    return False


def progetti_visibili(user, qs=None):
    """Progetti che l'utente vede: tutti con il permesso vedi_tutti_progetti, altrimenti quelli di cui è
    responsabile o membro."""
    qs = Progetto.objects.all() if qs is None else qs
    if user.is_superuser or user.has_perm("progetti.vedi_tutti_progetti"):
        return qs
    return qs.filter(pk__in=Progetto.objects.filter(Q(responsabile=user) | Q(membri=user)).values("pk"))
