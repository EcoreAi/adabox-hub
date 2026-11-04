import datetime
import re
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from core import cifratura


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
    livechat = models.BooleanField("chat con un cliente esterno", default=False, editable=False)
    origine = models.CharField("da dove arriva", max_length=10, blank=True, editable=False, help_text="sito, whatsapp o telegram")
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

    def get_origine_display_breve(self):
        return {"whatsapp": "WhatsApp", "telegram": "Telegram"}.get(self.origine, "")

    def titolo_per(self, utente):
        """Il nome mostrato: per i messaggi diretti, gli altri partecipanti (o il nome del gruppo, se ne ha uno)."""
        if self.livechat:
            return self.nome
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
    autore_esterno = models.CharField("scritto da (visitatore del sito)", max_length=80, blank=True)
    da_ai = models.BooleanField("scritto dall'assistente del sito", default=False)
    fonti = models.JSONField("fonti usate dall'assistente", default=list, blank=True)
    IN_CODA, INVIATO, CONSEGNATO, LETTO, NON_RIUSCITO, FUORI_FINESTRA = "in_coda", "inviato", "consegnato", "letto", "errore", "finestra"
    STATI_CONSEGNA = {IN_CODA: "Invio in corso", INVIATO: "Inviato", CONSEGNATO: "Consegnato", LETTO: "Letto", NON_RIUSCITO: "Non consegnato", FUORI_FINESTRA: "Non inviato"}
    consegna = models.CharField("consegna al cliente", max_length=10, blank=True)
    consegna_errore = models.CharField("motivo", max_length=200, blank=True)
    id_uscita = models.CharField("id sulla piattaforma", max_length=128, blank=True, db_index=True)
    dati_modello = models.JSONField("modello WhatsApp usato", default=dict, blank=True)
    parti_inviate = models.JSONField("parti già consegnate", default=list, blank=True, help_text="Per non rimandare nulla quando un invio si ritenta.")
    trascrizione = models.TextField("trascrizione del vocale", blank=True)
    trascrizione_stato = models.CharField("stato della trascrizione", max_length=10, blank=True)

    class Meta:
        verbose_name = "messaggio"
        verbose_name_plural = "messaggi"
        ordering = ["pk"]
        indexes = [models.Index(fields=["canale", "id"])]

    def __str__(self):
        return f"{self.autore}: {self.corpo[:40]}"

    @property
    def consegna_testo(self):
        return self.STATI_CONSEGNA.get(self.consegna, "")

    @property
    def nome_mittente(self):
        if self.autore_esterno:
            return self.autore_esterno
        return (self.autore.get_full_name() or self.autore.username) if self.autore else "Utente rimosso"


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
    registrando = models.BooleanField("registrazione in corso", default=False)
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


class Riassunto(models.Model):
    """Il riassunto di una conversazione chiesto da una persona: lo vede solo lei."""
    IN_CORSO, PRONTO, ERRORE = "in_corso", "pronto", "errore"
    canale = models.ForeignKey(Canale, on_delete=models.CASCADE, related_name="riassunti")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    stato = models.CharField("stato", max_length=10, default=IN_CORSO)
    ambito = models.CharField("periodo", max_length=10, default="oggi")
    n_messaggi = models.PositiveIntegerField("messaggi letti", default=0)
    testo = models.TextField("testo", blank=True)
    errore = models.CharField("errore", max_length=300, blank=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta:
        verbose_name = "riassunto"
        verbose_name_plural = "riassunti"
        ordering = ["-pk"]


class Registrazione(models.Model):
    """L'audio di una riunione, la sua trascrizione e cosa ne è uscito."""
    TRASCRIVO, PRONTA, SOLO_AUDIO, ERRORE = "trascrivo", "pronta", "solo_audio", "errore"
    chiamata = models.ForeignKey(Chiamata, on_delete=models.CASCADE, related_name="registrazioni")
    avviata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    stato = models.CharField("stato", max_length=10, default=TRASCRIVO)
    trascrizione = models.TextField("trascrizione", blank=True)
    sintesi = models.TextField("sintesi", blank=True)
    errore = models.CharField("errore", max_length=300, blank=True)
    creata = models.DateTimeField("creata il", auto_now_add=True)

    class Meta:
        verbose_name = "registrazione"
        verbose_name_plural = "registrazioni"
        ordering = ["-pk"]


def _nuova_chiave():
    return secrets.token_urlsafe(16)


class Sportello(models.Model):
    """La chat di un sito: chi risponde, cosa dice e quali siti possono ospitarla."""
    nome = models.CharField("nome", max_length=80, help_text="Compare in testa alla chat, es. «Assistenza clienti».")
    benvenuto = models.CharField("messaggio di benvenuto", max_length=300, default="Ciao! Come possiamo aiutarti?")
    assenza = models.CharField("se non c'è nessuno online", max_length=300, default="Ora non c'è nessuno online: lasciaci un messaggio e la tua email, ti rispondiamo appena possibile.")
    operatori = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="sportelli_discuss", verbose_name="operatori",
                                       help_text="Chi riceve le chat: ognuno vede tutte quelle di questo sportello.")
    domini = models.TextField("siti ammessi", blank=True, help_text="Un dominio per riga, es. www.azienda.it. Vuoto: la chat non si può incorporare in nessun sito.")
    privacy_url = models.URLField("informativa privacy", blank=True, help_text="Il link che il visitatore vede prima di scrivere.")
    TUTTI, A_TURNO = "tutti", "turno"
    distribuzione = models.CharField("come si distribuiscono le chat", max_length=10, default=TUTTI, choices=[
        (TUTTI, "Le vedono tutti gli operatori: le prende chi è libero"), (A_TURNO, "Vanno da sole all'operatore collegato con meno chat aperte")])
    PERSONE, AI, SOLO_AI = "persone", "ai", "solo_ai"
    MODALITA = [(PERSONE, "Rispondono le persone"), (AI, "Risponde l'AI, e passa a una persona quando serve"),
                (SOLO_AI, "Risponde solo l'AI")]
    modalita = models.CharField("chi risponde", max_length=10, choices=MODALITA, default=PERSONE)
    nome_ai = models.CharField("nome dell'assistente", max_length=60, default="Assistente virtuale")
    istruzioni = models.TextField("istruzioni per l'AI", blank=True, help_text="Facoltative: chi siete e con che tono rispondere. Le informazioni vanno nella Conoscenza del sito.")
    risposte_per_chat = models.PositiveIntegerField("risposte AI per conversazione", default=20, help_text="Oltre, passa a una persona.")
    risposte_al_giorno = models.PositiveIntegerField("risposte AI al giorno", default=300, help_text="Il tetto contro gli abusi: oltre, passa alle persone.")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="azienda", help_text="A chi vanno i costi dell'AI e quale tetto di spesa vale.")
    chiave = models.CharField("chiave", max_length=40, unique=True, default=_nuova_chiave, editable=False)
    attivo = models.BooleanField("attivo", default=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta:
        verbose_name = "sportello livechat"
        verbose_name_plural = "sportelli livechat"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class ConversazioneEsterna(models.Model):
    """Un visitatore del sito: si riconosce dal suo token, l'unica cosa che gli dà accesso alla sua conversazione."""
    sportello = models.ForeignKey(Sportello, on_delete=models.CASCADE, related_name="conversazioni")
    canale = models.OneToOneField(Canale, on_delete=models.CASCADE, related_name="esterna")
    token = models.CharField("token", max_length=64, unique=True)
    nome = models.CharField("nome", max_length=80)
    email = models.EmailField("email", blank=True)
    pagina = models.CharField("pagina di provenienza", max_length=300, blank=True)
    PERSONA, AI = "persona", "ai"
    gestita_da = models.CharField("chi sta rispondendo", max_length=10, default=PERSONA)
    risposte_ai = models.PositiveIntegerField("risposte dell'AI", default=0)
    connessione = models.ForeignKey("Connessione", on_delete=models.CASCADE, null=True, blank=True, related_name="conversazioni")
    assegnata_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_assegnate", verbose_name="assegnata a")
    id_esterno = models.CharField("numero o chat", max_length=64, blank=True, db_index=True)
    ultimo_in_arrivo = models.DateTimeField("ultimo messaggio del cliente", null=True, blank=True)
    impronta_ip = models.CharField("impronta dell'indirizzo", max_length=64, db_index=True, help_text="Solo per fermare gli abusi: l'indirizzo non si conserva.")
    ultimo_visto = models.DateTimeField("ultima visita", auto_now_add=True)
    creata = models.DateTimeField("creata il", auto_now_add=True, db_index=True)
    chiusa = models.DateTimeField("chiusa il", null=True, blank=True)

    @property
    def fuori_finestra(self):
        """WhatsApp: oltre le 24 ore dall'ultimo messaggio del cliente si possono mandare solo modelli approvati."""
        if self.connessione is None or self.connessione.tipo != Connessione.WHATSAPP or self.ultimo_in_arrivo is None:
            return False
        return timezone.now() - self.ultimo_in_arrivo > datetime.timedelta(hours=24)

    class Meta:
        verbose_name = "conversazione dal sito"
        verbose_name_plural = "conversazioni dal sito"
        ordering = ["-pk"]


class Connessione(models.Model):
    """Un numero WhatsApp o un bot Telegram che porta i clienti in uno sportello."""
    WHATSAPP, TELEGRAM = "whatsapp", "telegram"
    tipo = models.CharField("tipo", max_length=10, choices=[(WHATSAPP, "WhatsApp"), (TELEGRAM, "Telegram")])
    nome = models.CharField("nome", max_length=80, help_text="Per riconoscerla, es. «Numero assistenza».")
    sportello = models.ForeignKey(Sportello, on_delete=models.CASCADE, related_name="connessioni", verbose_name="sportello",
                                  help_text="Decide chi risponde: operatori, AI e conoscenza.")
    sandbox = models.BooleanField("connessione di prova", default=True, help_text="Non esce nulla in rete: si prova tutto dalla sandbox.")
    attiva = models.BooleanField("attiva", default=True)
    id_numero = models.CharField("ID del numero WhatsApp", max_length=64, blank=True, help_text="Il «Phone number ID» di Meta. Non serve per Telegram.")
    id_account = models.CharField("ID dell'account WhatsApp Business", max_length=64, blank=True, help_text="Serve per i modelli di messaggio approvati da Meta.")
    token_cifrato = models.TextField(blank=True, editable=False)
    segreto_cifrato = models.TextField(blank=True, editable=False)
    verifica = models.CharField("token di verifica", max_length=64, default=_nuova_chiave, editable=False)
    chiave = models.CharField("chiave dell'indirizzo", max_length=40, unique=True, default=_nuova_chiave, editable=False)
    sandbox_guasto = models.CharField(max_length=10, blank=True, editable=False)
    ultimo_evento = models.DateTimeField("ultimo messaggio ricevuto", null=True, blank=True, editable=False)
    ultimo_errore = models.CharField("ultimo errore", max_length=300, blank=True, editable=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)

    class Meta:
        verbose_name = "connessione"
        verbose_name_plural = "connessioni"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.get_tipo_display()})"

    def save(self, *args, **kwargs):
        if not self.segreto_cifrato:               # senza un segreto nessun messaggio supererebbe il controllo
            self.segreto_cifrato = cifratura.cifra(secrets.token_urlsafe(32))
        super().save(*args, **kwargs)

    def token(self):
        return cifratura.decifra(self.token_cifrato)

    def segreto(self):
        return cifratura.decifra(self.segreto_cifrato)


class ModelloWhatsApp(models.Model):
    """Un testo approvato da Meta: l'unico modo di scrivere a un cliente dopo le 24 ore dal suo ultimo messaggio."""
    IN_ATTESA, APPROVATO, RIFIUTATO = "in_attesa", "approvato", "rifiutato"
    STATI = [(IN_ATTESA, "In attesa di Meta"), (APPROVATO, "Approvato"), (RIFIUTATO, "Rifiutato")]
    UTILITY, MARKETING = "UTILITY", "MARKETING"
    connessione = models.ForeignKey(Connessione, on_delete=models.CASCADE, related_name="modelli", verbose_name="connessione", limit_choices_to={"tipo": Connessione.WHATSAPP})
    nome = models.CharField("nome", max_length=80, validators=[RegexValidator(r"^[a-z0-9_]+$", "Solo minuscole, cifre e trattino basso: lo chiede Meta.")], help_text="Es. ripresa_contatto")
    lingua = models.CharField("lingua", max_length=10, default="it")
    categoria = models.CharField("categoria", max_length=12, default=UTILITY, choices=[(UTILITY, "Servizio (aggiornamenti su una richiesta)"), (MARKETING, "Marketing (serve il consenso del cliente)")])
    corpo = models.TextField("testo", max_length=1024, help_text="Le parti variabili si scrivono {{1}}, {{2}}… Il testo non si può cambiare senza una nuova approvazione.")
    stato = models.CharField("stato", max_length=10, choices=STATI, default=IN_ATTESA, editable=False)
    motivo = models.CharField("motivo", max_length=300, blank=True, editable=False)
    aggiornato = models.DateTimeField("aggiornato il", auto_now=True)

    class Meta:
        verbose_name = "modello WhatsApp"
        verbose_name_plural = "modelli WhatsApp"
        ordering = ["nome"]
        constraints = [models.UniqueConstraint(fields=["connessione", "nome", "lingua"], name="discuss_modello_unico")]

    def __str__(self):
        return f"{self.nome} ({self.lingua})"

    @property
    def n_variabili(self):
        return len(set(re.findall(r"\{\{(\d+)\}\}", self.corpo)))

    def clean(self):
        numeri = sorted(int(n) for n in set(re.findall(r"\{\{(\d+)\}\}", self.corpo or "")))
        if numeri != list(range(1, len(numeri) + 1)):
            raise ValidationError({"corpo": "Le parti variabili vanno numerate senza salti: {{1}}, {{2}}…"})

    def componi(self, valori):
        testo = self.corpo
        for i, v in enumerate(valori, 1):
            testo = testo.replace("{{%d}}" % i, v)
        return testo


class EventoEsterno(models.Model):
    """I messaggi già visti: le piattaforme ne ripetono alcuni e un cliente non deve risultare scritto due volte."""
    connessione = models.ForeignKey(Connessione, on_delete=models.CASCADE, related_name="+")
    id_esterno = models.CharField(max_length=128)
    creato = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "evento esterno"
        verbose_name_plural = "eventi esterni"
        constraints = [models.UniqueConstraint(fields=["connessione", "id_esterno"], name="discuss_evento_esterno_unico")]


class SandboxMedia(models.Model):
    """Un file passato dalla sandbox: fa le veci dei server di Meta e Telegram."""
    connessione = models.ForeignKey(Connessione, on_delete=models.CASCADE, related_name="+")
    id_media = models.CharField(max_length=64, unique=True)
    nome = models.CharField(max_length=160)
    mime = models.CharField(max_length=100)
    dati = models.BinaryField()
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "file della sandbox"
        verbose_name_plural = "file della sandbox"


class SandboxEvento(models.Model):
    """Ciò che è passato nella sandbox, così com'è passato."""
    ENTRATA, USCITA = "entrata", "uscita"
    connessione = models.ForeignKey(Connessione, on_delete=models.CASCADE, related_name="+")
    contatto = models.CharField(max_length=64)
    verso = models.CharField(max_length=10)
    testo = models.TextField(blank=True)
    richiesta = models.JSONField(default=dict)
    risposta = models.JSONField(default=dict)
    codice = models.PositiveSmallIntegerField(default=200)
    media = models.ForeignKey(SandboxMedia, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    creato = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento della sandbox"
        verbose_name_plural = "eventi della sandbox"
        ordering = ["pk"]


class VoceConoscenza(models.Model):
    """Ciò che l'AI del sito può dire. Sta in tabelle sue: i record e i documenti interni non sono raggiungibili da lì."""
    FAQ, DOCUMENTO = "faq", "documento"
    sportello = models.ForeignKey(Sportello, on_delete=models.CASCADE, related_name="conoscenza", verbose_name="sportello")
    tipo = models.CharField("tipo", max_length=10, choices=[(FAQ, "Domanda frequente"), (DOCUMENTO, "Documento")], default=FAQ)
    titolo = models.CharField("titolo o domanda", max_length=200)
    testo = models.TextField("testo o risposta", help_text="Tutto ciò che scrivi qui può essere detto ai visitatori.")
    attiva = models.BooleanField("attiva", default=True)
    n_frammenti = models.PositiveIntegerField("frammenti", default=0, editable=False)
    aggiornata = models.DateTimeField("aggiornata il", auto_now=True)

    class Meta:
        verbose_name = "voce della conoscenza del sito"
        verbose_name_plural = "conoscenza del sito"
        ordering = ["tipo", "titolo"]

    def __str__(self):
        return self.titolo


class FrammentoPubblico(models.Model):
    voce = models.ForeignKey(VoceConoscenza, on_delete=models.CASCADE, related_name="frammenti")
    ordine = models.PositiveIntegerField(default=0)
    testo = models.TextField()
    vettore = models.BinaryField(null=True, blank=True)

    class Meta:
        verbose_name = "frammento pubblico"
        verbose_name_plural = "frammenti pubblici"
        ordering = ["voce", "ordine"]


class DomandaSenzaRisposta(models.Model):
    """Dove l'AI non ha saputo rispondere: dice cosa aggiungere alla conoscenza."""
    sportello = models.ForeignKey(Sportello, on_delete=models.CASCADE, related_name="senza_risposta")
    conversazione = models.ForeignKey(ConversazioneEsterna, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    testo = models.TextField("domanda")
    risolta = models.BooleanField("risolta", default=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)

    class Meta:
        verbose_name = "domanda senza risposta"
        verbose_name_plural = "domande senza risposta"
        ordering = ["-pk"]
