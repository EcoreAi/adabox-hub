import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.mixins import AziendaMixin


class Evento(AziendaMixin):
    PROMEMORIA = [(0, "Nessuno"), (15, "15 minuti prima"), (60, "1 ora prima"), (1440, "1 giorno prima")]
    uid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    titolo = models.CharField("titolo", max_length=200)
    inizio = models.DateTimeField("inizio")
    fine = models.DateTimeField("fine")
    tutto_il_giorno = models.BooleanField("tutto il giorno", default=False)
    luogo = models.CharField("luogo", max_length=200, blank=True)
    descrizione = models.TextField("descrizione", blank=True)
    organizzatore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="eventi_organizzati", verbose_name="organizzatore")
    partecipanti = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="eventi",
                                          verbose_name="partecipanti")
    contatti = models.ManyToManyField("contatti.Contatto", blank=True, related_name="eventi", verbose_name="contatti")
    privato = models.BooleanField("privato", default=False, help_text="visibile solo a organizzatore e partecipanti")
    promemoria = models.PositiveIntegerField("promemoria", choices=PROMEMORIA, default=15)
    promemoria_inviato = models.BooleanField(default=False, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "evento"
        verbose_name_plural = "eventi"
        ordering = ["inizio"]

    def __str__(self):
        return self.titolo

    def clean(self):
        if self.inizio and self.fine and self.fine < self.inizio:
            raise ValidationError({"fine": "La fine non può precedere l'inizio."})


class TipoAppuntamento(AziendaMixin):
    """Un appuntamento che i clienti prenotano da soli dalla pagina pubblica: durata, operatori e orari."""
    nome = models.CharField("nome", max_length=100, help_text="es. «Consulenza di 30 minuti»")
    codice = models.SlugField("indirizzo", max_length=60, unique=True,
                              help_text="la parte finale del link pubblico, es. consulenza")
    descrizione = models.TextField("descrizione", blank=True, help_text="mostrata sulla pagina di prenotazione")
    durata = models.PositiveIntegerField("durata (minuti)", default=30)
    pausa = models.PositiveIntegerField("pausa dopo (minuti)", default=0, help_text="tempo libero tra un appuntamento e l'altro")
    luogo = models.CharField("luogo", max_length=200, blank=True, help_text="indirizzo, telefono o link della videochiamata")
    operatori = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="tipi_appuntamento", verbose_name="operatori",
                                       help_text="chi riceve gli appuntamenti: si sceglie il primo libero")
    preavviso = models.PositiveIntegerField("preavviso minimo (ore)", default=2)
    giorni_avanti = models.PositiveIntegerField("prenotabile fino a (giorni)", default=30)
    crea_opportunita = models.BooleanField("crea un'opportunità", default=False,
                                           help_text="con il CRM installato, ogni prenotazione apre un'opportunità")
    promemoria = models.PositiveIntegerField("promemoria", choices=Evento.PROMEMORIA, default=1440)
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "tipo di appuntamento"
        verbose_name_plural = "tipi di appuntamento"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def clean(self):
        if self.durata and self.durata < 5:
            raise ValidationError({"durata": "Almeno 5 minuti."})


class OrarioAppuntamento(models.Model):
    GIORNI = [(0, "Lunedì"), (1, "Martedì"), (2, "Mercoledì"), (3, "Giovedì"), (4, "Venerdì"), (5, "Sabato"), (6, "Domenica")]
    tipo = models.ForeignKey(TipoAppuntamento, on_delete=models.CASCADE, related_name="orari", verbose_name="tipo")
    giorno = models.PositiveSmallIntegerField("giorno", choices=GIORNI)
    dalle = models.TimeField("dalle")
    alle = models.TimeField("alle")

    class Meta:
        verbose_name = "orario"
        verbose_name_plural = "orari"
        ordering = ["giorno", "dalle"]

    def __str__(self):
        return f"{self.get_giorno_display()} {self.dalle:%H:%M}-{self.alle:%H:%M}"

    def clean(self):
        if self.dalle and self.alle and self.alle <= self.dalle:
            raise ValidationError({"alle": "L'orario di fine deve venire dopo l'inizio."})


class Prenotazione(AziendaMixin):
    CONFERMATA, ANNULLATA = "confermata", "annullata"
    STATI = [(CONFERMATA, "Confermata"), (ANNULLATA, "Annullata")]
    tipo = models.ForeignKey(TipoAppuntamento, on_delete=models.PROTECT, related_name="prenotazioni", verbose_name="tipo")
    inizio = models.DateTimeField("inizio")
    fine = models.DateTimeField("fine")
    operatore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="prenotazioni_ricevute", verbose_name="operatore")
    evento = models.OneToOneField(Evento, on_delete=models.SET_NULL, null=True, blank=True, related_name="prenotazione",
                                  verbose_name="evento")
    nome = models.CharField("nome", max_length=200)
    email = models.EmailField("email")
    telefono = models.CharField("telefono", max_length=40, blank=True)
    societa = models.CharField("azienda", max_length=200, blank=True)
    note = models.TextField("note", blank=True)
    contatto = models.ForeignKey("contatti.Contatto", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="prenotazioni", verbose_name="contatto")
    opportunita_id = models.PositiveIntegerField("opportunità", null=True, blank=True, editable=False)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=CONFERMATA)
    promemoria_inviato = models.BooleanField(default=False, editable=False)
    creata_il = models.DateTimeField("creata il", auto_now_add=True)
    annullata_il = models.DateTimeField("annullata il", null=True, blank=True, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "prenotazione"
        verbose_name_plural = "prenotazioni"
        ordering = ["-inizio"]

    def __str__(self):
        return f"{self.tipo} · {self.nome}"
