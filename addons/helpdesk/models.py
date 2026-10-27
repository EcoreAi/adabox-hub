from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin, ProprietaMixin


class Team(models.Model):
    nome = models.CharField("nome", max_length=80, unique=True)
    membri = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="team_helpdesk",
                                    verbose_name="membri")

    class Meta:
        verbose_name = "team"
        verbose_name_plural = "team"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class FaseTicket(models.Model):
    nome = models.CharField("nome", max_length=60)
    ordine = models.PositiveSmallIntegerField("ordine", default=10)
    chiusa = models.BooleanField("chiude il ticket", default=False)

    class Meta:
        verbose_name = "fase"
        verbose_name_plural = "fasi"
        ordering = ["ordine", "pk"]

    def __str__(self):
        return self.nome


def fase_iniziale():
    return FaseTicket.objects.order_by("ordine", "pk").values_list("pk", flat=True).first()


class Ticket(AziendaMixin, ProprietaMixin):
    BASSA, MEDIA, ALTA, URGENTE = "bassa", "media", "alta", "urgente"
    PRIORITA = [(BASSA, "Bassa"), (MEDIA, "Media"), (ALTA, "Alta"), (URGENTE, "Urgente")]
    numero = models.CharField("numero", max_length=30, blank=True, editable=False, db_index=True)
    oggetto = models.CharField("oggetto", max_length=200)
    descrizione = models.TextField("descrizione", blank=True)
    contatto = models.ForeignKey("contatti.Contatto", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="ticket", verbose_name="cliente")
    email_cliente = models.EmailField("email del cliente", blank=True,
                                      help_text="riceve i messaggi del ticket e può rispondere per email")
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="team")
    assegnatario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="ticket_assegnati", verbose_name="assegnatario")
    fase = models.ForeignKey(FaseTicket, on_delete=models.PROTECT, default=fase_iniziale, verbose_name="fase")
    priorita = models.CharField("priorità", max_length=8, choices=PRIORITA, default=MEDIA)
    creato = models.DateTimeField("aperto il", auto_now_add=True)
    scadenza_sla = models.DateTimeField("scadenza SLA", null=True, blank=True, editable=False)
    sla_avvisato = models.BooleanField(default=False, editable=False)
    chiuso_il = models.DateTimeField("chiuso il", null=True, blank=True, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "ticket"
        verbose_name_plural = "ticket"
        ordering = ["-creato", "-pk"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._priorita_caricata = self.priorita

    def __str__(self):
        return f"{self.numero} {self.oggetto}".strip()

    @property
    def aperto(self):
        return not self.fase.chiusa

    def ore_sla(self):
        from core import parametri
        try:
            return parametri.leggi(f"helpdesk.ore_{self.priorita}", self.azienda)
        except KeyError:
            return {"urgente": 4, "alta": 8, "media": 24, "bassa": 72}[self.priorita]

    def save(self, *args, **kwargs):
        from core import sequenze
        extra = set()
        if not self.numero:
            self.numero = sequenze.prossimo("helpdesk.ticket", self.azienda)
            extra.add("numero")
        if self.pk is None or self.priorita != self._priorita_caricata:
            partenza = self.creato or timezone.now()
            self.scadenza_sla, self.sla_avvisato = partenza + timedelta(hours=self.ore_sla()), False
            extra |= {"scadenza_sla", "sla_avvisato"}
        if self.fase_id and self.fase.chiusa:
            self.chiuso_il = self.chiuso_il or timezone.now()
        else:
            self.chiuso_il = None
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | extra | {"chiuso_il"}
        super().save(*args, **kwargs)
        self._priorita_caricata = self.priorita
