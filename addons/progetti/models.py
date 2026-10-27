from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, Q

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

    def riepilogo_compiti(self):
        """(totale, completati, percentuale, [(fase, numero)])."""
        per_fase = list(FaseCompito.objects.annotate(n=Count("compiti", filter=Q(compiti__progetto=self))))
        totale = sum(f.n for f in per_fase)
        completati = sum(f.n for f in per_fase if f.chiusa)
        return totale, completati, round(100 * completati / totale) if totale else 0, [(f, f.n) for f in per_fase]


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


def progetti_visibili(user, qs=None):
    """Progetti che l'utente vede: tutti con il permesso vedi_tutti_progetti, altrimenti quelli di cui è
    responsabile o membro."""
    qs = Progetto.objects.all() if qs is None else qs
    if user.is_superuser or user.has_perm("progetti.vedi_tutti_progetti"):
        return qs
    return qs.filter(pk__in=Progetto.objects.filter(Q(responsabile=user) | Q(membri=user)).values("pk"))
