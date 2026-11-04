from django.conf import settings
from django.db import models


class Canale(models.Model):
    """Conversazione: canale pubblico (chiunque entra), privato (su invito) o diretto (tra persone scelte)."""
    PUBBLICO, PRIVATO, DIRETTO = "pubblico", "privato", "diretto"
    TIPI = [(PUBBLICO, "Pubblico"), (PRIVATO, "Privato"), (DIRETTO, "Diretto")]
    nome = models.CharField("nome", max_length=80, blank=True)
    descrizione = models.CharField("descrizione", max_length=250, blank=True)
    tipo = models.CharField("tipo", max_length=10, choices=TIPI, default=PUBBLICO)
    membri = models.ManyToManyField(settings.AUTH_USER_MODEL, through="Iscrizione", related_name="canali_discuss",
                                    verbose_name="membri")
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="creato da", editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    archiviato = models.BooleanField("archiviato", default=False)
    gestito = models.BooleanField("canale gestito", default=False,
                                  help_text="Scrivono solo amministratori, moderatori e contributori; gli altri leggono.")
    lista_email = models.BooleanField("lista email", default=False,
                                      help_text="I messaggi arrivano per email agli iscritti, che rispondono dalla propria casella.")
    vocale = models.BooleanField("canale vocale", default=False, help_text="Una stanza sempre aperta: si entra e si parla, senza squilli.")
    record_ct = models.ForeignKey("contenttypes.ContentType", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                  verbose_name="tipo del record", help_text="Se il canale è la conversazione su un record.")
    record_id = models.PositiveBigIntegerField("record", null=True, blank=True)

    class Meta:
        verbose_name = "canale"
        verbose_name_plural = "canali"
        ordering = ["nome", "pk"]

    def __str__(self):
        return self.nome or f"Conversazione {self.pk}"

    @property
    def diretto(self):
        return self.tipo == self.DIRETTO

    def titolo_per(self, utente):
        """Il nome mostrato: per i messaggi diretti, gli altri partecipanti (o il nome del gruppo, se ne ha uno)."""
        if not self.diretto:
            return f"# {self.nome}"
        if self.nome:
            return self.nome
        altri = [u.get_full_name() or u.username for u in self.membri.all() if u.pk != utente.pk]
        return ", ".join(altri) or "Solo tu"


class Iscrizione(models.Model):
    TUTTO, MENZIONI, NIENTE = "tutto", "menzioni", "niente"
    NOTIFICHE = [(TUTTO, "Tutti i messaggi"), (MENZIONI, "Solo le menzioni"), (NIENTE, "Niente")]
    canale = models.ForeignKey(Canale, on_delete=models.CASCADE, related_name="iscrizioni")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="iscrizioni_discuss")
    ultimo_letto = models.PositiveBigIntegerField("ultimo messaggio letto", default=0)
    notifiche = models.CharField("notifiche", max_length=10, choices=NOTIFICHE, default=MENZIONI)
    entrato = models.DateTimeField(auto_now_add=True)
    AMMINISTRATORE, MODERATORE, CONTRIBUTORE, MEMBRO = "amministratore", "moderatore", "contributore", "membro"
    RUOLI = [(AMMINISTRATORE, "Amministratore"), (MODERATORE, "Moderatore"), (CONTRIBUTORE, "Contributore"),
             (MEMBRO, "Membro")]
    ruolo = models.CharField("ruolo", max_length=15, choices=RUOLI, default=MEMBRO)
    fissata = models.BooleanField("tra i preferiti", default=False)
    tieni_non_letto = models.BooleanField("segnata da leggere", default=False)

    class Meta:
        verbose_name = "iscrizione"
        verbose_name_plural = "iscrizioni"
        constraints = [models.UniqueConstraint(fields=["canale", "utente"], name="discuss_iscrizione_unica")]


class Messaggio(models.Model):
    canale = models.ForeignKey(Canale, on_delete=models.CASCADE, related_name="messaggi", verbose_name="canale")
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+",
                               verbose_name="autore")
    corpo = models.TextField("testo", blank=True)
    creato = models.DateTimeField("inviato il", auto_now_add=True)
    modificato_il = models.DateTimeField("modificato il", null=True, blank=True)
    eliminato = models.BooleanField("eliminato", default=False)
    NORMALE, SISTEMA = "normale", "sistema"
    tipo = models.CharField("tipo", max_length=10, choices=[(NORMALE, "Messaggio"), (SISTEMA, "Avviso")], default=NORMALE)
    risposta_a = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="risposte",
                                   verbose_name="risponde a")
    fissato_il = models.DateTimeField("fissato il", null=True, blank=True)
    fissato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="fissato da")
    anteprime = models.JSONField("anteprime dei link", default=list, blank=True)

    class Meta:
        verbose_name = "messaggio"
        verbose_name_plural = "messaggi"
        ordering = ["pk"]
        indexes = [models.Index(fields=["canale", "id"])]

    def __str__(self):
        return f"{self.autore}: {self.corpo[:40]}"


class Notifica(models.Model):
    """Voce della posta in arrivo: una menzione, un messaggio diretto, un messaggio su un record seguito."""
    MENZIONE, DIRETTO, CANALE, RECORD, RISPOSTA, ATTIVITA = "menzione", "diretto", "canale", "record", "risposta", "attivita"
    TIPI = [(MENZIONE, "Menzione"), (DIRETTO, "Messaggio diretto"), (CANALE, "Messaggio nel canale"),
            (RECORD, "Messaggio su un record seguito"), (RISPOSTA, "Risposta a un tuo messaggio"), (ATTIVITA, "Attività assegnata")]
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifiche_discuss")
    tipo = models.CharField("tipo", max_length=10, choices=TIPI)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+")
    messaggio = models.ForeignKey(Messaggio, on_delete=models.CASCADE, null=True, blank=True, related_name="notifiche")
    messaggio_chatter = models.ForeignKey("core.Messaggio", on_delete=models.CASCADE, null=True, blank=True,
                                          related_name="+")
    titolo = models.CharField("titolo", max_length=200)
    testo = models.TextField("anteprima", blank=True)
    url = models.CharField("link", max_length=300)
    letta = models.BooleanField("letta", default=False)
    email_inviata = models.BooleanField("email inviata", default=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)

    class Meta:
        verbose_name = "notifica"
        verbose_name_plural = "notifiche"
        ordering = ["-creata", "-pk"]
        indexes = [models.Index(fields=["utente", "letta"])]


class Collegamento(models.Model):
    """Un record citato da un messaggio: nella conversazione diventa una scheda, sul record una voce della cronologia."""
    messaggio = models.ForeignKey(Messaggio, on_delete=models.CASCADE, related_name="collegamenti")
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE, related_name="+")
    object_id = models.PositiveBigIntegerField()

    class Meta:
        verbose_name = "record collegato"
        verbose_name_plural = "record collegati"
        ordering = ["pk"]
        indexes = [models.Index(fields=["content_type", "object_id"])]
        constraints = [models.UniqueConstraint(fields=["messaggio", "content_type", "object_id"], name="discuss_collegamento_unico")]


class Reazione(models.Model):
    messaggio = models.ForeignKey(Messaggio, on_delete=models.CASCADE, related_name="reazioni")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    emoji = models.CharField("emoji", max_length=16)

    class Meta:
        verbose_name = "reazione"
        verbose_name_plural = "reazioni"
        ordering = ["pk"]
        constraints = [models.UniqueConstraint(fields=["messaggio", "utente", "emoji"], name="discuss_reazione_unica")]


class Presenza(models.Model):
    """Se una persona è collegata e se ha scelto uno stato: online e assente si calcolano da questi due istanti."""
    AUTO, OCCUPATO, ASSENTE = "auto", "occupato", "assente"
    STATI = [(AUTO, "Automatico"), (OCCUPATO, "Non disturbare"), (ASSENTE, "Assente")]
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="presenza_discuss")
    ultimo_visto = models.DateTimeField("ultimo collegamento", null=True, blank=True)
    ultima_attivita = models.DateTimeField("ultima attività", null=True, blank=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=AUTO)
    fuori_fino = models.DateField("fuori ufficio fino al", null=True, blank=True)
    messaggio = models.CharField("messaggio di stato", max_length=140, blank=True)

    class Meta:
        verbose_name = "presenza"
        verbose_name_plural = "presenze"


class Evento(models.Model):
    """Ciò che arriva in tempo reale ai browser: si legge in ordine di id, e dopo un giorno si butta."""
    canale = models.ForeignKey(Canale, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True, related_name="+",
                               help_text="Se indicato, l'evento è solo per questa persona.")
    tipo = models.CharField("tipo", max_length=20)
    dati = models.JSONField("dati", default=dict, blank=True)
    creato = models.DateTimeField("creato il", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "evento"
        verbose_name_plural = "eventi"
        ordering = ["pk"]


class Chiamata(models.Model):
    """Audio e video tra browser: il server fa solo da centralino, i media vanno da persona a persona."""
    canale = models.ForeignKey(Canale, on_delete=models.CASCADE, related_name="chiamate")
    avviata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    token = models.CharField("codice", max_length=64, unique=True)
    video = models.BooleanField("video", default=True)
    ospiti_ammessi = models.BooleanField("ospiti esterni", default=False)
    iniziata = models.DateTimeField("iniziata il", auto_now_add=True)
    finita = models.DateTimeField("finita il", null=True, blank=True)

    class Meta:
        verbose_name = "chiamata"
        verbose_name_plural = "chiamate"
        ordering = ["-pk"]


class Partecipante(models.Model):
    chiamata = models.ForeignKey(Chiamata, on_delete=models.CASCADE, related_name="partecipanti")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               help_text="Vuoto per un ospite esterno.")
    nome = models.CharField("nome", max_length=80)
    segreto = models.CharField("segreto", max_length=64, unique=True)
    ammesso = models.BooleanField("ammesso", default=False)
    microfono = models.BooleanField(default=True)
    camera = models.BooleanField(default=True)
    schermo = models.BooleanField(default=False)
    mano = models.BooleanField(default=False)
    entrato = models.DateTimeField(auto_now_add=True)
    ultimo_visto = models.DateTimeField(auto_now_add=True)
    uscito = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "partecipante"
        verbose_name_plural = "partecipanti"
        ordering = ["pk"]


class Segnale(models.Model):
    """Ciò che i browser si dicono per collegarsi e cosa cambia in chiamata. `a` vuoto: per tutti i presenti."""
    chiamata = models.ForeignKey(Chiamata, on_delete=models.CASCADE, related_name="segnali")
    da = models.ForeignKey(Partecipante, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    a = models.ForeignKey(Partecipante, on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    tipo = models.CharField(max_length=20)
    dati = models.JSONField(default=dict, blank=True)
    creato = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "segnale"
        verbose_name_plural = "segnali"
        ordering = ["pk"]
