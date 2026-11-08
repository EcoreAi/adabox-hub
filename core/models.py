import hashlib
import re
import secrets
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from .mixins import ProprietaMixin
from .storage import StoragePrivato


class Azienda(ProprietaMixin):
    nome = models.CharField("nome", max_length=160)
    partita_iva = models.CharField("partita IVA", max_length=16, blank=True)
    codice_fiscale = models.CharField("codice fiscale", max_length=16, blank=True)
    indirizzo = models.CharField("indirizzo", max_length=200, blank=True)
    cap = models.CharField("CAP", max_length=10, blank=True)
    citta = models.CharField("città", max_length=100, blank=True)
    provincia = models.CharField("provincia", max_length=2, blank=True)
    email = models.EmailField("email", blank=True)
    telefono = models.CharField("telefono", max_length=40, blank=True)
    logo = models.ImageField("logo", upload_to="aziende/", blank=True)
    attiva = models.BooleanField("attiva", default=True)

    class Meta:
        verbose_name = "azienda"
        verbose_name_plural = "aziende"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class DashboardUtente(models.Model):
    """La dashboard come l'ha disposta l'utente: ordine e larghezza dei widget, e quelli che ha tolto."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dashboard", verbose_name="utente")
    layout = models.JSONField("disposizione", default=dict, blank=True,
                              help_text='{"widget": [{"id": "todo:kpi", "w": 1}, …], "nascosti": ["crm:g0", …]}')
    aggiornato = models.DateTimeField("aggiornata il", auto_now=True)

    class Meta:
        verbose_name = "dashboard dell'utente"
        verbose_name_plural = "dashboard degli utenti"

    def __str__(self):
        return f"dashboard di {self.utente}"


class Ruolo(models.Model):
    """Che cosa può fare una persona in ogni modulo: un livello di partenza e, dove serve, un livello diverso per modulo.
    I livelli diventano i gruppi Django dei moduli (vedi core.ruoli)."""
    LIVELLI = [("nessuno", "Nessun accesso"), ("lettura", "Sola lettura"), ("lavoro", "Lavoro"), ("responsabile", "Responsabile")]
    nome = models.CharField("nome", max_length=60, unique=True)
    descrizione = models.CharField("descrizione", max_length=200, blank=True)
    livello_base = models.CharField("livello in tutti i moduli", max_length=12, choices=LIVELLI, default="lavoro")
    livelli = models.JSONField("livelli per modulo", default=dict, blank=True, help_text="{slug del modulo: livello}, dove il ruolo si discosta dal livello base")
    amministra = models.BooleanField("amministra la piattaforma", default=False,
                                     help_text="utenti, ruoli, impostazioni e admin di Django")
    tecnico = models.BooleanField("accesso tecnico completo", default=False,
                                  help_text="superutente: anche moduli, lavori e tutto l'admin di Django; per chi gestisce la piattaforma")
    predefinito = models.BooleanField("ai nuovi utenti", default=False, help_text="il ruolo di chi viene creato senza sceglierne uno")
    dashboard = models.JSONField("dashboard iniziale", default=dict, blank=True,
                                 help_text="la disposizione da cui parte la dashboard di chi ha questo ruolo e non l'ha ancora personalizzata")
    ordine = models.PositiveSmallIntegerField("ordine", default=10)

    class Meta:
        verbose_name = "ruolo"
        verbose_name_plural = "ruoli"
        ordering = ["ordine", "nome"]

    def __str__(self):
        return self.nome


class ProfiloUtente(models.Model):
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profilo")
    ruolo = models.ForeignKey(Ruolo, on_delete=models.SET_NULL, null=True, blank=True, related_name="profili", verbose_name="ruolo",
                              help_text="vuoto: i gruppi si gestiscono a mano, come prima dei ruoli")
    eccezioni = models.JSONField("eccezioni per modulo", default=dict, blank=True, help_text="{slug del modulo: livello} che vince sul ruolo")
    aziende = models.ManyToManyField(Azienda, verbose_name="aziende consentite", blank=True)
    azienda_predefinita = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True,
                                            related_name="+", verbose_name="azienda predefinita")
    esterno = models.BooleanField("utente esterno", default=False,
                                  help_text="un cliente: vede solo il portale, mai le pagine interne")
    barra = models.JSONField("app nella barra", default=dict, blank=True, help_text='{"fisse": [slug, ...]}: l\'ordine scelto da questa persona; vuoto = quello dell\'azienda')

    class Meta:
        verbose_name = "profilo utente"
        verbose_name_plural = "profili utente"

    def __str__(self):
        return f"profilo di {self.utente}"


class DueFattori(models.Model):
    """Autenticazione a due fattori di un utente: segreto TOTP cifrato e codici di recupero (solo le impronte)."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="due_fattori",
                                  verbose_name="utente")
    segreto_cifrato = models.TextField("segreto cifrato", editable=False)
    attiva_dal = models.DateTimeField("attiva dal", null=True, blank=True, editable=False,
                                      help_text="vuoto finché la procedura di attivazione non è conclusa")
    codici_recupero = models.JSONField("codici di recupero", default=list, editable=False)
    ultimo_passo = models.BigIntegerField("ultimo passo usato", default=0, editable=False,
                                          help_text="un codice già usato non vale una seconda volta")
    fallimenti = models.PositiveSmallIntegerField("tentativi falliti", default=0, editable=False)
    bloccata_fino = models.DateTimeField("bloccata fino a", null=True, blank=True, editable=False)
    generazione = models.PositiveIntegerField("generazione dei dispositivi fidati", default=1, editable=False)

    class Meta:
        verbose_name = "autenticazione a due fattori"
        verbose_name_plural = "autenticazioni a due fattori"

    def __str__(self):
        return f"2FA di {self.utente}"


class SpostamentoKanban(models.Model):
    """Una scheda spostata a mano tra le colonne di un kanban: chi, da dove a dove, quando, con una nota se c'è."""
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE, verbose_name="tipo")
    object_id = models.PositiveBigIntegerField("record")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="spostata da")
    da = models.CharField("da", max_length=120, blank=True)
    a = models.CharField("a", max_length=120, blank=True)
    nota = models.TextField("nota", blank=True)
    quando = models.DateTimeField("quando", auto_now_add=True)

    class Meta:
        verbose_name = "spostamento nel kanban"
        verbose_name_plural = "spostamenti nel kanban"
        ordering = ["-quando", "-pk"]
        indexes = [models.Index(fields=["content_type", "object_id", "-quando"])]

    def __str__(self):
        return f"{self.da} → {self.a}"


class LicenzaIstanza(models.Model):
    """La licenza di questa istanza e l'ultimo catalogo ricevuti dal portale (una riga sola)."""
    testo = models.TextField("file di licenza", blank=True)
    catalogo = models.JSONField("catalogo", default=dict, blank=True)
    ultima_sincronia = models.DateTimeField("ultima sincronizzazione", null=True, blank=True)
    ultimo_errore = models.TextField("ultimo errore", blank=True)
    ultimo_esito = models.JSONField("ultime operazioni", default=list, blank=True)
    aggiornata = models.DateTimeField("aggiornata il", auto_now=True)

    class Meta:
        verbose_name = "licenza dell'istanza"
        verbose_name_plural = "licenza dell'istanza"


class RichiestaModulo(models.Model):
    """Un'app del catalogo chiesta dall'amministratore del cliente: la decide ICHNOBYTE sul portale."""
    INVIATA, EVASA, RIFIUTATA = "inviata", "evasa", "rifiutata"
    INSTALLAZIONE, DEMO = "installazione", "demo"
    TIPI = [(INSTALLAZIONE, "Installazione"), (DEMO, "Demo")]
    tipo = models.CharField("tipo", max_length=15, choices=TIPI, default=INSTALLAZIONE)
    STATI = [(INVIATA, "Inviata"), (EVASA, "Attivata"), (RIFIUTATA, "Non accolta")]
    slug = models.SlugField("modulo", max_length=31)
    nome = models.CharField("nome", max_length=120)
    nota = models.TextField("nota", blank=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="chiesta da")
    stato = models.CharField("stato", max_length=10, choices=STATI, default=INVIATA)
    consegnata = models.BooleanField("arrivata al portale", default=False)
    creata = models.DateTimeField("chiesta il", auto_now_add=True)

    class Meta:
        verbose_name = "richiesta di modulo"
        verbose_name_plural = "richieste di moduli"
        ordering = ["-creata"]

    def __str__(self):
        return self.nome


class Modulo(models.Model):
    DISPONIBILE, INSTALLATO, DA_AGGIORNARE, MANCANTE, ERRORE = (
        "disponibile", "installato", "da_aggiornare", "mancante", "errore")
    STATI = [(DISPONIBILE, "Disponibile"), (INSTALLATO, "Installato"), (DA_AGGIORNARE, "Da aggiornare"),
             (MANCANTE, "Mancante"), (ERRORE, "Errore")]
    slug = models.SlugField("slug", max_length=31, unique=True)
    nome = models.CharField("nome", max_length=120)
    versione_installata = models.CharField("versione installata", max_length=20, blank=True)
    versione_disponibile = models.CharField("versione disponibile", max_length=20, blank=True)
    stato = models.CharField("stato", max_length=20, choices=STATI, default=DISPONIBILE)
    application = models.BooleanField("app", default=False)
    installato_il = models.DateTimeField("installato il", null=True, blank=True)
    aggiornato_il = models.DateTimeField("aggiornato il", null=True, blank=True)
    gruppi_creati = models.JSONField("gruppi creati", default=list, blank=True)
    ultimo_errore = models.TextField("ultimo errore", blank=True)
    etichetta = models.CharField("nome nel menu", max_length=40, blank=True, help_text="scelto dall'Admin; vuoto = quello del modulo")
    disattivato = models.BooleanField("disattivato", default=False,
                                      help_text="installato ma spento per tutti: menu, pagine, API e pianificazioni")

    class Meta:
        verbose_name = "modulo"
        verbose_name_plural = "moduli"
        ordering = ["nome"]

    def __str__(self):
        return f"{self.nome} ({self.slug})"


class TokenApi(models.Model):
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="token_api")
    nome = models.CharField("nome", max_length=80)
    chiave = models.CharField("chiave (hash)", max_length=64, unique=True, editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    ultimo_uso = models.DateTimeField("ultimo uso", null=True, blank=True)
    attivo = models.BooleanField("attivo", default=True)
    scadenza = models.DateField("valido fino al", null=True, blank=True, help_text="vuoto = senza scadenza")
    sola_lettura = models.BooleanField("sola lettura", default=False)
    moduli = models.JSONField("solo questi moduli", default=list, blank=True, help_text="vuoto = tutti quelli che l'utente vede")

    class Meta:
        verbose_name = "token API"
        verbose_name_plural = "token API"
        ordering = ["-creato"]

    def __str__(self):
        return f"{self.nome} ({self.utente})"

    @staticmethod
    def _hash(chiaro):
        return hashlib.sha256(chiaro.encode()).hexdigest()

    @classmethod
    def genera(cls, utente, nome, scadenza=None, sola_lettura=False, moduli=()):
        chiaro = secrets.token_urlsafe(32)
        return cls.objects.create(utente=utente, nome=nome, chiave=cls._hash(chiaro), scadenza=scadenza,
                                  sola_lettura=sola_lettura, moduli=list(moduli)), chiaro

    @property
    def scaduto(self):
        return self.scadenza is not None and self.scadenza < timezone.localdate()

    def permette(self, modulo, scrittura):
        """Il token restringe ciò che l'utente può fare, non lo allarga mai: i permessi dell'utente valgono comunque."""
        return (not scrittura or not self.sola_lettura) and (not self.moduli or modulo in self.moduli)

    @classmethod
    def verifica(cls, chiaro):
        token = (cls.objects.filter(chiave=cls._hash(chiaro), attivo=True, utente__is_active=True)
                 .select_related("utente").first())
        if token and token.scaduto:
            return None
        if token:
            cls.objects.filter(pk=token.pk).update(ultimo_uso=timezone.now())
        return token


class Lavoro(models.Model):
    """Lavoro in background: una funzione Python con argomenti JSON, eseguita dal worker."""
    IN_CODA, IN_CORSO, FATTO, FALLITO = "in_coda", "in_corso", "fatto", "fallito"
    STATI = [(IN_CODA, "In coda"), (IN_CORSO, "In corso"), (FATTO, "Fatto"), (FALLITO, "Fallito")]
    funzione = models.CharField("funzione", max_length=200)
    argomenti = models.JSONField("argomenti", default=dict, blank=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=IN_CODA)
    tentativi = models.PositiveSmallIntegerField("tentativi", default=0)
    max_tentativi = models.PositiveSmallIntegerField("tentativi massimi", default=3)
    esegui_dopo = models.DateTimeField("esegui dopo", default=timezone.now)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    iniziato = models.DateTimeField("iniziato il", null=True, blank=True)
    finito = models.DateTimeField("finito il", null=True, blank=True)
    errore = models.TextField("errore", blank=True)
    risultato = models.TextField("risultato", blank=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="azienda")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+", verbose_name="utente")

    class Meta:
        verbose_name = "lavoro"
        verbose_name_plural = "lavori"
        ordering = ["-creato", "-pk"]
        indexes = [models.Index(fields=["stato", "esegui_dopo"])]

    def __str__(self):
        return f"{self.funzione} #{self.pk}"


class Pianificazione(models.Model):
    """Lavoro ricorrente dichiarato nel manifest di un modulo (o dal kernel): il worker lo accoda quando scade."""
    modulo = models.CharField("modulo", max_length=31)
    nome = models.CharField("nome", max_length=120)
    funzione = models.CharField("funzione", max_length=200)
    ogni = models.CharField("ogni", max_length=10, help_text="15m, 1h, 1d…")
    alle = models.CharField("alle", max_length=5, blank=True, help_text="HH:MM, solo per gli intervalli in giorni")
    attiva = models.BooleanField("attiva", default=True)
    prossima_esecuzione = models.DateTimeField("prossima esecuzione", null=True, blank=True)
    ultima_esecuzione = models.DateTimeField("ultima esecuzione", null=True, blank=True)

    class Meta:
        verbose_name = "pianificazione"
        verbose_name_plural = "pianificazioni"
        ordering = ["modulo", "nome"]
        constraints = [models.UniqueConstraint(fields=["modulo", "nome"], name="pianificazione_unica")]

    def __str__(self):
        return f"{self.modulo}: {self.nome}"


class Parametro(models.Model):
    """Valore di un'impostazione dichiarata nel manifest (`settings`): globale o per azienda."""
    chiave = models.CharField("chiave", max_length=100, help_text="<modulo>.<nome>")
    valore = models.JSONField("valore", null=True, blank=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.CASCADE, null=True, blank=True, verbose_name="azienda")

    class Meta:
        verbose_name = "parametro"
        verbose_name_plural = "parametri"
        ordering = ["chiave"]
        constraints = [
            models.UniqueConstraint(fields=["chiave"], condition=models.Q(azienda__isnull=True),
                                    name="parametro_globale_unico"),
            models.UniqueConstraint(fields=["chiave", "azienda"], condition=models.Q(azienda__isnull=False),
                                    name="parametro_azienda_unico"),
        ]

    def __str__(self):
        return f"{self.chiave} = {self.valore!r}" + (f" ({self.azienda})" if self.azienda_id else "")


class Sequenza(models.Model):
    """Numerazione progressiva (es. ATT/2026/0001), per azienda o globale (azienda vuota)."""
    MAI, ANNO = "mai", "anno"
    codice = models.CharField("codice", max_length=100, help_text="<modulo>.<nome>")
    azienda = models.ForeignKey(Azienda, on_delete=models.CASCADE, null=True, blank=True, verbose_name="azienda")
    formato = models.CharField("formato", max_length=100, help_text="{anno} {mese:02d} {numero:05d}")
    prossimo = models.PositiveIntegerField("prossimo numero", default=1)
    azzera = models.CharField("azzera", max_length=4, choices=[(MAI, "Mai"), (ANNO, "Ogni anno")], default=MAI)
    anno = models.PositiveSmallIntegerField("anno corrente", null=True, blank=True)

    class Meta:
        verbose_name = "sequenza"
        verbose_name_plural = "sequenze"
        ordering = ["codice"]
        constraints = [
            models.UniqueConstraint(fields=["codice"], condition=models.Q(azienda__isnull=True),
                                    name="sequenza_globale_unica"),
            models.UniqueConstraint(fields=["codice", "azienda"], condition=models.Q(azienda__isnull=False),
                                    name="sequenza_azienda_unica"),
        ]

    def __str__(self):
        return f"{self.codice}" + (f" ({self.azienda})" if self.azienda_id else "")


def _percorso_allegato(instance, filename):
    return f"allegati/{timezone.now():%Y/%m}/{uuid.uuid4().hex}-{filename}"


class Allegato(models.Model):
    """File allegato a un record qualsiasi; privato: si scarica solo con il permesso di vedere il record."""
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    file = models.FileField("file", upload_to=_percorso_allegato, storage=StoragePrivato(), max_length=300)
    nome = models.CharField("nome", max_length=200)
    mime = models.CharField("tipo", max_length=100, blank=True)
    dimensione = models.PositiveBigIntegerField("dimensione", default=0)
    caricato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="caricato da")
    creato = models.DateTimeField("caricato il", auto_now_add=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="azienda")

    class Meta:
        verbose_name = "allegato"
        verbose_name_plural = "allegati"
        ordering = ["-creato", "-pk"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return self.nome


class Messaggio(models.Model):
    """Voce del chatter di un record: nota interna, messaggio ai follower, tracciamento, evento di sistema."""
    NOTA, MESSAGGIO, TRACCIAMENTO, SISTEMA = "nota", "messaggio", "tracciamento", "sistema"
    TIPI = [(NOTA, "Nota"), (MESSAGGIO, "Messaggio"), (TRACCIAMENTO, "Tracciamento"), (SISTEMA, "Sistema")]
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    tipo = models.CharField("tipo", max_length=12, choices=TIPI, default=MESSAGGIO)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="+", verbose_name="autore")
    autore_email = models.EmailField("email dell'autore", blank=True, help_text="mittente esterno (non utente)")
    corpo = models.TextField("testo", blank=True)
    modifiche = models.JSONField("modifiche", default=list, blank=True)
    allegati = models.ManyToManyField(Allegato, blank=True, related_name="messaggi", verbose_name="allegati")
    message_id = models.CharField("Message-ID", max_length=255, blank=True, db_index=True)
    destinatari = models.JSONField("anche a", default=list, blank=True,
                                   help_text="indirizzi esterni scelti da chi ha scritto, oltre ai follower")
    fissato = models.BooleanField("fissato", default=False, help_text="resta in cima ai messaggi del record")
    creato = models.DateTimeField("creato il", default=timezone.now)

    class Meta:
        verbose_name = "messaggio"
        verbose_name_plural = "messaggi"
        ordering = ["-creato", "-pk"]
        indexes = [models.Index(fields=["content_type", "object_id", "-creato"])]

    def __str__(self):
        return f"{self.get_tipo_display()} di {self.autore or 'sistema'} ({self.creato:%d/%m/%Y %H:%M})"


class Follower(models.Model):
    """Chi segue un record: riceve per email i messaggi (non le note)."""
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="segue")

    class Meta:
        verbose_name = "follower"
        verbose_name_plural = "follower"
        constraints = [models.UniqueConstraint(fields=["content_type", "object_id", "utente"], name="follower_unico")]

    def __str__(self):
        return f"{self.utente} segue {self.content_type.model} #{self.object_id}"


class EmailRicevuta(models.Model):
    """Email arrivata nella casella delle risposte: esito dell'abbinamento a un record del chatter."""
    ABBINATA, NON_ABBINATA, RIFIUTATA, ERRORE = "abbinata", "non_abbinata", "rifiutata", "errore"
    STATI = [(ABBINATA, "Abbinata"), (NON_ABBINATA, "Non abbinata"), (RIFIUTATA, "Rifiutata"), (ERRORE, "Errore")]
    message_id = models.CharField("Message-ID", max_length=255, unique=True)
    mittente = models.CharField("mittente", max_length=254, blank=True)
    oggetto = models.CharField("oggetto", max_length=255, blank=True)
    ricevuta = models.DateTimeField("ricevuta il", auto_now_add=True)
    stato = models.CharField("stato", max_length=12, choices=STATI)
    motivo = models.TextField("motivo", blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    messaggio = models.ForeignKey(Messaggio, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="messaggio")

    class Meta:
        verbose_name = "email ricevuta"
        verbose_name_plural = "email ricevute"
        ordering = ["-ricevuta", "-pk"]

    def __str__(self):
        return f"{self.oggetto or '(senza oggetto)'} da {self.mittente}"


class TipoAttivita(models.Model):
    nome = models.CharField("nome", max_length=60, unique=True)
    icona = models.CharField("icona", max_length=30, default="check", help_text="nome di un'icona del theme")
    giorni = models.PositiveSmallIntegerField("giorni di default", default=0)
    ordine = models.PositiveSmallIntegerField("ordine", default=10)

    class Meta:
        verbose_name = "tipo di attività"
        verbose_name_plural = "tipi di attività"
        ordering = ["ordine", "nome"]

    def __str__(self):
        return self.nome


class AttivitaPianificata(models.Model):
    """Cosa da fare su un record (chiamata, email, riunione...), con scadenza e assegnatario.
    Quando si segna fatta diventa una voce del chatter e la riga sparisce."""
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    record = GenericForeignKey("content_type", "object_id")
    tipo = models.ForeignKey(TipoAttivita, on_delete=models.PROTECT, verbose_name="tipo")
    riepilogo = models.CharField("riepilogo", max_length=200, blank=True)
    nota = models.TextField("nota", blank=True)
    scadenza = models.DateField("scadenza")
    assegnatario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                     related_name="attivita_pianificate", verbose_name="assegnatario")
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="creata da")
    creato = models.DateTimeField("creata il", auto_now_add=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="azienda")

    class Meta:
        verbose_name = "attività pianificata"
        verbose_name_plural = "attività pianificate"
        ordering = ["scadenza", "pk"]
        indexes = [models.Index(fields=["content_type", "object_id"]), models.Index(fields=["assegnatario", "scadenza"])]

    def __str__(self):
        return f"{self.tipo}: {self.riepilogo or self.record}"


class CampoPersonalizzato(models.Model):
    """Campo aggiunto dal cliente a un modello con ProprietaMixin, per tutte le aziende o per una sola."""
    TESTO, INTERO, DECIMALE, BOOLEANO, DATA, SCELTA, UTENTE = (
        "testo", "intero", "decimale", "booleano", "data", "scelta", "utente")
    TIPI = [(TESTO, "Testo"), (INTERO, "Numero intero"), (DECIMALE, "Numero decimale"), (BOOLEANO, "Sì/No"),
            (DATA, "Data"), (SCELTA, "Scelta da elenco"), (UTENTE, "Utente")]
    modello = models.ForeignKey(ContentType, on_delete=models.CASCADE, verbose_name="modello")
    nome = models.SlugField("nome tecnico", max_length=40, help_text="minuscole, cifre e _ (es. codice_cliente)")
    label = models.CharField("etichetta", max_length=80)
    tipo = models.CharField("tipo", max_length=10, choices=TIPI, default=TESTO)
    scelte = models.TextField("scelte", blank=True, help_text="una per riga: valore|etichetta (solo per le scelte)")
    aiuto = models.CharField("testo di aiuto", max_length=200, blank=True)
    obbligatorio = models.BooleanField("obbligatorio", default=False)
    in_lista = models.BooleanField("mostra nella lista", default=False)
    filtrabile = models.BooleanField("filtrabile", default=False, help_text="per scelte, Sì/No e utenti")
    ordine = models.PositiveSmallIntegerField("ordine", default=10)
    azienda = models.ForeignKey(Azienda, on_delete=models.CASCADE, null=True, blank=True, verbose_name="azienda",
                                help_text="vuoto = per tutte le aziende")

    class Meta:
        verbose_name = "campo personalizzato"
        verbose_name_plural = "campi personalizzati"
        ordering = ["modello", "ordine", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["modello", "nome"], condition=models.Q(azienda__isnull=True),
                                    name="campo_globale_unico"),
            models.UniqueConstraint(fields=["modello", "nome", "azienda"], condition=models.Q(azienda__isnull=False),
                                    name="campo_azienda_unico"),
        ]

    def __str__(self):
        return f"{self.label} ({self.modello.name})"

    def clean(self):
        from django.core.exceptions import ValidationError
        errori = {}
        if self.nome and not re.match(r"^[a-z][a-z0-9_]*$", self.nome):
            errori["nome"] = "Solo lettere minuscole, cifre e _, iniziando con una lettera."
        modello = self.modello.model_class() if self.modello_id else None
        if modello is not None and not any(f.name == "proprieta" for f in modello._meta.get_fields()):
            errori["modello"] = "Questo modello non accetta campi personalizzati."
        if self.tipo == self.SCELTA and not self.elenco_scelte():
            errori["scelte"] = "Indica almeno una scelta (valore|etichetta)."
        if self.filtrabile and self.tipo not in (self.SCELTA, self.BOOLEANO, self.UTENTE):
            errori["filtrabile"] = "Si possono filtrare solo scelte, Sì/No e utenti."
        if errori:
            raise ValidationError(errori)

    def elenco_scelte(self):
        voci = []
        for riga in self.scelte.splitlines():
            if riga.strip():
                valore, _, etichetta = riga.partition("|")
                voci.append((valore.strip(), (etichetta or valore).strip()))
        return voci


class ModelloEmail(models.Model):
    """Il testo di un'email scritto dall'azienda: sostituisce quello del modulo, o è un modello suo per le automazioni
    (allora ha `dominio`, il tipo di record su cui si usa, e `nome`)."""
    azienda = models.ForeignKey(Azienda, on_delete=models.CASCADE, related_name="modelli_email", verbose_name="azienda")
    codice = models.CharField("codice", max_length=80)
    nome = models.CharField("nome", max_length=120, blank=True)
    dominio = models.CharField("si usa su", max_length=30, blank=True)
    oggetto = models.CharField("oggetto", max_length=250)
    corpo = models.TextField("testo")
    aggiornato = models.DateTimeField("modificato il", auto_now=True)
    aggiornato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+", verbose_name="modificato da")

    class Meta:
        verbose_name = "modello di email"
        verbose_name_plural = "modelli di email"
        ordering = ["nome", "codice"]
        constraints = [models.UniqueConstraint(fields=["azienda", "codice"], name="modello_email_unico")]

    def __str__(self):
        return self.nome or self.codice


class RicercaSalvata(models.Model):
    """Una ricerca di una lista, da riaprire con un clic: personale o condivisa con chi lavora nella stessa azienda."""
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, verbose_name="azienda")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ricerche_salvate", verbose_name="proprietario")
    vista = models.CharField("vista", max_length=70, db_index=True, help_text="modulo.slug")
    nome = models.CharField("nome", max_length=80)
    parametri = models.TextField("parametri", blank=True, help_text="la parte dopo il ? dell'indirizzo della lista")
    condivisa = models.BooleanField("condivisa con l'azienda", default=False)
    predefinita = models.BooleanField("si apre da sola", default=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)

    class Meta:
        verbose_name = "ricerca salvata"
        verbose_name_plural = "ricerche salvate"
        ordering = ["nome", "pk"]
        constraints = [models.UniqueConstraint(fields=["azienda", "utente", "vista", "nome"], name="core_ricerca_unica")]

    def __str__(self):
        return self.nome


class RegistroModifica(models.Model):
    """Chi ha cambiato cosa, quando e da dove: una riga per ogni salvataggio o eliminazione dei record con una vista.
    Si aggiunge e basta: dalle pagine e dall'API non si modifica né si cancella."""
    CREATO, AGGIORNATO, ELIMINATO = "creato", "aggiornato", "eliminato"
    AZIONI = [(CREATO, "Creato"), (AGGIORNATO, "Aggiornato"), (ELIMINATO, "Eliminato")]
    ORIGINI = [("ui", "Pagine"), ("api", "API"), ("ai", "Assistente"), ("worker", "Lavoro in background"), ("sistema", "Sistema")]
    azienda = models.ForeignKey("core.Azienda", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="azienda")
    content_type = models.ForeignKey("contenttypes.ContentType", on_delete=models.CASCADE, verbose_name="tipo di record")
    object_id = models.PositiveBigIntegerField("record", db_index=True)
    oggetto = models.CharField("record", max_length=200)
    azione = models.CharField("azione", max_length=10, choices=AZIONI)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="utente")
    utente_nome = models.CharField("nome dell'utente", max_length=150, blank=True, help_text="resta anche se l'utente viene eliminato")
    origine = models.CharField("origine", max_length=8, choices=ORIGINI, default="sistema")
    modifiche = models.JSONField("modifiche", default=list, blank=True)
    creato = models.DateTimeField("quando", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "modifica"
        verbose_name_plural = "registro delle modifiche"
        ordering = ["-creato", "-pk"]
        indexes = [models.Index(fields=["content_type", "object_id", "-creato"]), models.Index(fields=["azienda", "-creato"])]

    def __str__(self):
        return f"{self.oggetto}: {self.get_azione_display().lower()}"


class PermessoCampo(models.Model):
    """Un campo di una vista nascosto o in sola lettura per chi ha un ruolo: vale in form, dettaglio, lista, export, API
    e per l'assistente (core.regole). Il superuser vede e modifica tutto."""
    NASCOSTO, SOLA_LETTURA = "nascosto", "lettura"
    LIVELLI = [(NASCOSTO, "Nascosto"), (SOLA_LETTURA, "Sola lettura")]
    vista = models.CharField("vista", max_length=80, help_text="modulo.slug, es. crm.opportunita")
    campo = models.CharField("campo", max_length=80)
    ruolo = models.ForeignKey(Ruolo, on_delete=models.CASCADE, related_name="permessi_campo", verbose_name="ruolo")
    livello = models.CharField("livello", max_length=10, choices=LIVELLI, default=NASCOSTO)

    class Meta:
        verbose_name = "permesso su un campo"
        verbose_name_plural = "permessi sui campi"
        ordering = ["vista", "campo"]
        constraints = [models.UniqueConstraint(fields=["vista", "campo", "ruolo"], name="permesso_campo_unico")]

    def __str__(self):
        return f"{self.vista}.{self.campo}: {self.get_livello_display().lower()} per {self.ruolo}"


class RegolaRiga(models.Model):
    """Quali record di una vista vede chi ha un ruolo (es. «solo le opportunità di cui è commerciale»): un filtro
    applicato al queryset della vista, quindi anche a liste, API, export e assistente. Più regole: valgono tutte."""
    OPERATORI = [("utente", "è l'utente che guarda"), ("uguale", "è uguale a"), ("diverso", "è diverso da"),
                 ("in", "è uno tra (separati da virgola)"), ("vuoto", "è vuoto"), ("pieno", "non è vuoto"),
                 ("contiene", "contiene"), ("min", "è almeno"), ("max", "è al massimo")]
    vista = models.CharField("vista", max_length=80, help_text="modulo.slug, es. crm.opportunita")
    ruolo = models.ForeignKey(Ruolo, on_delete=models.CASCADE, related_name="regole_righe", verbose_name="ruolo")
    campo = models.CharField("campo", max_length=120, help_text="anche attraverso le relazioni, es. progetto__responsabile")
    operatore = models.CharField("condizione", max_length=10, choices=OPERATORI, default="utente")
    valore = models.CharField("valore", max_length=200, blank=True)
    attiva = models.BooleanField("attiva", default=True)

    class Meta:
        verbose_name = "regola sulle righe"
        verbose_name_plural = "regole sulle righe"
        ordering = ["vista", "ruolo__nome"]

    def __str__(self):
        return f"{self.vista}: {self.campo} {self.get_operatore_display()} {self.valore}".strip()


class ModelloStampa(models.Model):
    """Come si stampa un documento (un report di una vista) per un'azienda: colore, righe sotto l'intestazione, piè di
    pagina, testi prima e dopo il corpo con segnaposto {{ campo }}, colonne nascoste. Senza modello: la stampa originale."""
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, null=True, blank=True, related_name="modelli_stampa",
                                verbose_name="azienda", help_text="vuoto = per tutte le aziende che non ne hanno uno proprio")
    report = models.CharField("documento", max_length=120, help_text="modulo.slug:numero del report")
    colore = models.CharField("colore", max_length=7, blank=True, help_text="titoli e linee, es. #1e3a8a; vuoto = quello standard")
    mostra_logo = models.BooleanField("mostra il logo", default=True)
    righe_intestazione = models.TextField("righe sotto l'intestazione", blank=True,
                                          help_text="es. telefono, email, sito, REA, capitale sociale")
    testo_iniziale = models.TextField("testo prima del documento", blank=True)
    testo_finale = models.TextField("testo dopo il documento", blank=True, help_text="es. condizioni di vendita, coordinate bancarie")
    piede = models.CharField("piè di pagina", max_length=250, blank=True, help_text="vuoto = nome dell'applicazione e data di stampa")
    colonne_nascoste = models.JSONField("colonne nascoste", default=list, blank=True)
    attivo = models.BooleanField("attivo", default=True, help_text="spento = si stampa l'originale")
    aggiornato = models.DateTimeField("aggiornato il", auto_now=True)

    class Meta:
        verbose_name = "modello di stampa"
        verbose_name_plural = "modelli di stampa"
        ordering = ["report", "azienda__nome"]
        constraints = [models.UniqueConstraint(fields=["azienda", "report"], name="modello_stampa_unico")]

    def __str__(self):
        from core import stampe
        return f"{stampe.etichetta(self.report)} · {self.azienda or 'tutte le aziende'}"
