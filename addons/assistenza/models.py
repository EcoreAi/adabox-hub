import datetime
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.mixins import AziendaMixin


class PoliticaSLA(models.Model):
    """Tempi di un contratto: prima risposta e risoluzione per priorità, in ore lavorative o sulle 24 ore."""
    nome = models.CharField("nome", max_length=80, unique=True)
    risposta_urgente = models.PositiveIntegerField("prima risposta, urgente (ore)", default=1)
    risposta_alta = models.PositiveIntegerField("prima risposta, alta (ore)", default=4)
    risposta_media = models.PositiveIntegerField("prima risposta, media (ore)", default=8)
    risposta_bassa = models.PositiveIntegerField("prima risposta, bassa (ore)", default=16)
    risoluzione_urgente = models.PositiveIntegerField("risoluzione, urgente (ore)", default=8)
    risoluzione_alta = models.PositiveIntegerField("risoluzione, alta (ore)", default=24)
    risoluzione_media = models.PositiveIntegerField("risoluzione, media (ore)", default=40)
    risoluzione_bassa = models.PositiveIntegerField("risoluzione, bassa (ore)", default=80)
    ore_lavorative = models.BooleanField("conta solo le ore lavorative", default=True)
    inizio_giornata = models.TimeField("inizio della giornata", default=datetime.time(9, 0))
    fine_giornata = models.TimeField("fine della giornata", default=datetime.time(18, 0))
    giorni = models.CharField("giorni lavorativi", max_length=20, default="0,1,2,3,4",
                              help_text="0 = lunedì … 6 = domenica, separati da virgole")

    class Meta:
        verbose_name = "politica SLA"
        verbose_name_plural = "politiche SLA"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def ore(self, tipo, priorita):
        return getattr(self, f"{tipo}_{priorita}")

    def elenco_giorni(self):
        return {int(g) for g in self.giorni.split(",") if g.strip().isdigit() and 0 <= int(g) <= 6}


class Contratto(AziendaMixin):
    """Il contratto di assistenza di un cliente: la sua politica SLA, per un periodo."""
    nome = models.CharField("nome", max_length=120, help_text="es. Premium 2026")
    cliente = models.ForeignKey("contatti.Contatto", on_delete=models.PROTECT, related_name="contratti_assistenza",
                                verbose_name="cliente")
    politica = models.ForeignKey(PoliticaSLA, on_delete=models.PROTECT, verbose_name="politica SLA")
    inizio = models.DateField("dal", default=datetime.date.today)
    fine = models.DateField("al", null=True, blank=True, help_text="vuoto = senza scadenza")
    attivo = models.BooleanField("attivo", default=True)
    note = models.TextField("note", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "contratto"
        verbose_name_plural = "contratti"
        ordering = ["cliente__nome", "-inizio"]

    def __str__(self):
        return f"{self.nome} · {self.cliente}"

    @classmethod
    def valido_per(cls, contatto, giorno=None):
        """Il contratto valido oggi del cliente (o dell'azienda della persona)."""
        if contatto is None:
            return None
        giorno = giorno or timezone.localdate()
        clienti = [contatto.pk] + ([contatto.societa_id] if contatto.societa_id else [])
        return (cls.objects.filter(cliente__in=clienti, attivo=True, inizio__lte=giorno)
                .filter(models.Q(fine__isnull=True) | models.Q(fine__gte=giorno))
                .select_related("politica").order_by("-inizio").first())


def _chiave():
    return secrets.token_urlsafe(18)


class Supporto(AziendaMixin):
    """L'assistenza di un progetto: chi riceve i ticket, con quale contratto, da quali siti arriva il widget."""
    progetto = models.OneToOneField("progetti.Progetto", on_delete=models.CASCADE, related_name="supporto",
                                    verbose_name="progetto")
    team = models.ForeignKey("helpdesk.Team", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="team")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="responsabile dell'assistenza",
                                     help_text="riceve i ticket; vuoto = il membro del team con meno ticket aperti")
    contratto = models.ForeignKey(Contratto, on_delete=models.SET_NULL, null=True, blank=True,
                                  verbose_name="contratto", help_text="vuoto = il contratto valido del cliente")
    chiave = models.CharField("chiave del widget", max_length=40, unique=True, default=_chiave, editable=False)
    domini = models.TextField("siti ammessi per il widget", blank=True,
                              help_text="uno per riga, es. https://app.cliente.it; vuoto = widget spento")
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "supporto di un progetto"
        verbose_name_plural = "supporto dei progetti"
        ordering = ["progetto__nome"]

    def __str__(self):
        return f"Supporto · {self.progetto}"

    def elenco_domini(self):
        return [d.strip().rstrip("/").lower() for d in self.domini.splitlines() if d.strip()]

    def contratto_valido(self):
        if self.contratto_id and self.contratto.attivo:
            return self.contratto
        return Contratto.valido_per(self.progetto.cliente)


class DatiTicket(models.Model):
    """Quello che l'assistenza aggiunge a un ticket: progetto, compito, tipo, canale, dati tecnici, prima risposta."""
    BUG, RICHIESTA, DOMANDA = "bug", "richiesta", "domanda"
    TIPI = [(BUG, "Problema (bug)"), (RICHIESTA, "Richiesta di modifica"), (DOMANDA, "Domanda")]
    WIDGET, PORTALE, EMAIL, INTERNO = "widget", "portale", "email", "interno"
    CANALI = [(WIDGET, "Widget nell'applicazione"), (PORTALE, "Portale clienti"), (EMAIL, "Email"),
              (INTERNO, "Inserito internamente")]
    ticket = models.OneToOneField("helpdesk.Ticket", on_delete=models.CASCADE, related_name="assistenza",
                                  verbose_name="ticket")
    progetto = models.ForeignKey("progetti.Progetto", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="ticket_assistenza", verbose_name="progetto")
    compito = models.ForeignKey("progetti.Compito", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="ticket_assistenza", verbose_name="compito di sviluppo")
    tipo = models.CharField("tipo", max_length=10, choices=TIPI, default=BUG)
    canale = models.CharField("canale", max_length=8, choices=CANALI, default=INTERNO)
    tecnici = models.JSONField("dati tecnici", default=dict, blank=True,
                               help_text="pagina, browser, schermo, versione dell'applicazione, errori")
    scadenza_risposta = models.DateTimeField("scadenza della prima risposta", null=True, blank=True)
    risposta_il = models.DateTimeField("prima risposta", null=True, blank=True)

    class Meta:
        verbose_name = "dati di assistenza"
        verbose_name_plural = "dati di assistenza"

    def __str__(self):
        return f"Assistenza · {self.ticket}"


class AccessoPortale(models.Model):
    """L'accesso di un cliente al portale: un utente esterno legato a un contatto (persona di un'azienda cliente).
    Vede i ticket e i progetti della sua azienda."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accesso_portale",
                                  verbose_name="utente")
    contatto = models.ForeignKey("contatti.Contatto", on_delete=models.CASCADE, related_name="accessi_portale",
                                 verbose_name="contatto")
    invitato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="invitato da")
    invitato_il = models.DateTimeField("invitato il", auto_now_add=True)

    class Meta:
        verbose_name = "accesso al portale"
        verbose_name_plural = "accessi al portale"

    def __str__(self):
        return f"{self.utente} · {self.contatto}"

    @property
    def cliente(self):
        """L'azienda cliente (il contatto stesso se è un'azienda)."""
        return self.contatto.societa or self.contatto

    def contatti(self):
        """Il cliente e tutte le sue persone: i loro ticket sono visibili dal portale."""
        cliente = self.cliente
        return [cliente.pk, *cliente.persone.values_list("pk", flat=True)]
