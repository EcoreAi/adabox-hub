"""Dati di Agentic Workforce: il collegamento alla fabbrica, gli agenti, le operazioni ammesse, le approvazioni
di Agate in attesa e il registro delle chiamate degli agenti.

I segreti (token della fabbrica, segreto dei webhook di Agate) si salvano cifrati con `core.cifratura`; del bearer
del server MCP si tiene solo l'impronta SHA-256."""
from urllib.parse import urlsplit

from django.conf import settings
from django.db import models
from django.db.models import Q

from core import cifratura
from core.models import Azienda


class Collegamento(models.Model):
    """Il collegamento di questa istanza alla fabbrica degli agenti: una riga sola (pk=1)."""
    forge_url = models.URLField("indirizzo della fabbrica", blank=True)
    base_url = models.URLField("indirizzo pubblico di questa istanza", blank=True,
                               help_text="dove Agate raggiunge il server MCP e il webhook")
    install_id = models.CharField("id dell'installazione", max_length=100, blank=True)
    token_cifrato = models.TextField("token della fabbrica (cifrato)", blank=True, editable=False)
    segreto_webhook_cifrato = models.TextField("segreto dei webhook di Agate (cifrato)", blank=True, editable=False)
    mcp_impronta = models.CharField("impronta del bearer MCP", max_length=64, blank=True, editable=False)
    mcp_indizio = models.CharField("inizio del bearer MCP", max_length=12, blank=True, editable=False)
    versione = models.CharField("versione dichiarata", max_length=30, blank=True)
    ultimo_stato = models.JSONField("ultimo stato del contratto", default=dict, blank=True)
    stato_il = models.DateTimeField("ultimo battito riuscito", null=True, blank=True)
    ultimo_errore = models.CharField("ultimo errore", max_length=300, blank=True)
    collegato_il = models.DateTimeField("collegato il", null=True, blank=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name="azienda in cui lavorano gli agenti")
    agate_url = models.URLField("indirizzo della console di Agate", blank=True,
                                help_text="vuoto = quello indicato dalla fabbrica")
    factory_code_cifrato = models.TextField("codice per la fabbrica (cifrato)", blank=True, editable=False,
                                            help_text="agf_...: dal collegamento ad Agate con un codice, va in ogni "
                                                      "richiesta d'ingaggio")
    # Agate incluso (§8.6): la prova che adabox è davvero all'indirizzo dichiarato, pubblica finché la fabbrica la legge
    prova_incluso = models.CharField("prova per Agate incluso", max_length=40, blank=True, editable=False)
    prova_scade = models.DateTimeField("la prova scade il", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "collegamento"
        verbose_name_plural = "collegamento"

    def __str__(self):
        return f"Collegamento a {self.forge_url}" if self.forge_url else "Collegamento (non configurato)"

    @classmethod
    def attuale(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def collegato(self):
        return bool(self.token_cifrato)

    def token(self):
        return cifratura.decifra(self.token_cifrato)

    def segreto_webhook(self):
        return cifratura.decifra(self.segreto_webhook_cifrato)

    def factory_code(self):
        return cifratura.decifra(self.factory_code_cifrato)

    @property
    def ingaggio(self):
        return self.ultimo_stato if isinstance(self.ultimo_stato, dict) else {}

    @property
    def mcp_url(self):
        return f"{self.base_url.rstrip('/')}/awf/mcp/" if self.base_url else ""

    @property
    def webhook_url(self):
        return f"{self.base_url.rstrip('/')}/awf/agate-webhook/" if self.base_url else ""

    def console_agate(self):
        """L'origine della console di Agate (https://host), per i link alle approvazioni."""
        if self.agate_url:
            return self.agate_url.rstrip("/")
        link = self.ingaggio.get("agate_console_url")
        parti = urlsplit(link) if isinstance(link, str) else None
        if parti and parti.scheme in ("http", "https") and parti.netloc:
            return f"{parti.scheme}://{parti.netloc}"
        return ""


class Agente(models.Model):
    """Un agente del contratto (l'ingaggio della fabbrica), con il suo utente Django (`awf-<nome>`): attivo, senza password usabile, senza
    email, mai nell'interfaccia. Agisce solo nelle chiamate MCP che Agate ha già deciso."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agente_awf",
                                  verbose_name="utente")
    nome = models.CharField("nome", max_length=100)
    ruolo = models.CharField("ruolo", max_length=100, blank=True)
    agate_agent_id = models.CharField("id in Agate", max_length=100, blank=True, db_index=True)
    attivo = models.BooleanField("nel contratto", default=True,
                                 help_text="falso se la fabbrica non lo elenca più: le sue chiamate si rifiutano")
    tecnico = models.BooleanField("agente tecnico", default=False,
                                  help_text="usato quando la chiamata non indica un agente")
    creato = models.DateTimeField("creato il", auto_now_add=True)
    ultimo_uso = models.DateTimeField("ultima chiamata", null=True, blank=True)

    class Meta:
        verbose_name = "agente"
        verbose_name_plural = "agenti"
        ordering = ["-attivo", "nome"]

    def __str__(self):
        return self.nome


class OperazioneAmmessa(models.Model):
    """Una voce dell'elenco chiuso: uno strumento dell'assistente AI, su una vista o (vuota) su tutte quelle che
    gli agenti possono vedere. Nient'altro arriva agli agenti."""
    strumento = models.CharField("strumento", max_length=60)
    vista = models.CharField("vista", max_length=80, blank=True, help_text="es. todo.attivita; vuota = tutte")
    attiva = models.BooleanField("attiva", default=True)
    creato = models.DateTimeField("creata il", auto_now_add=True)
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", editable=False)

    class Meta:
        verbose_name = "operazione ammessa"
        verbose_name_plural = "operazioni ammesse"
        ordering = ["strumento", "vista"]
        constraints = [models.UniqueConstraint(fields=["strumento", "vista"], name="awf_operazione_unica")]

    def __str__(self):
        return f"{self.strumento} su {self.vista}" if self.vista else f"{self.strumento} (tutte le viste)"


class Approvazione(models.Model):
    """Un'approvazione chiesta in Agate (webhook `approval.requested`), chiusa da `approval.decided`.
    Collegato ad Agate con un codice si decide in adabox («Da approvare»), a nome di chi clicca; altrimenti nella
    console di Agate."""
    IN_ATTESA = "in_attesa"
    approval_id = models.CharField("id in Agate", max_length=64, unique=True)
    strumento = models.CharField("strumento", max_length=200, blank=True)
    riepilogo = models.TextField("riepilogo", blank=True, help_text="già mascherato da Agate")
    scade = models.DateTimeField("scade il", null=True, blank=True)
    stato = models.CharField("stato", max_length=20, default=IN_ATTESA)
    ricevuta = models.DateTimeField("ricevuta il", auto_now_add=True)
    decisa = models.DateTimeField("decisa il", null=True, blank=True)
    contratto = models.BooleanField("riguarda il contratto", default=False,
                                    help_text="rinnovo o cambio del contratto degli agenti, non un'azione")
    decisa_da = models.CharField("decisa da", max_length=200, blank=True)
    motivo = models.CharField("motivo", max_length=1000, blank=True)
    in_conferma = models.BooleanField("aspetta la doppia conferma", default=False,
                                      help_text="approvata in adabox: Agate ha scritto ai responsabili")
    parametri = models.JSONField("parametri dell'azione", default=dict, blank=True,
                                 help_text="se il webhook li porta (già mascherati da Agate): per dirla in parole")
    attore = models.CharField("chi la chiede", max_length=200, blank=True,
                              help_text="l'agente, se il webhook lo dice (id in Agate o nome)")

    class Meta:
        verbose_name = "approvazione"
        verbose_name_plural = "approvazioni"
        ordering = ["-ricevuta"]

    def __str__(self):
        return self.riepilogo[:80] or self.approval_id


class Chiamata(models.Model):
    """Registro delle chiamate degli agenti. Delle scritture tiene argomenti, anteprima ed esito (anche quelle
    ferme nel periodo di prova: «cosa sarebbe successo»); delle letture solo strumento, vista ed esito."""
    ESEGUITA, OSSERVAZIONE, RIFIUTATA, ERRORE = "eseguita", "osservazione", "rifiutata", "errore"
    ESITI = [(ESEGUITA, "Eseguita"), (OSSERVAZIONE, "Periodo di prova (non eseguita)"), (RIFIUTATA, "Rifiutata"),
             (ERRORE, "Errore")]
    creato = models.DateTimeField("il", auto_now_add=True, db_index=True)
    agente = models.ForeignKey(Agente, on_delete=models.SET_NULL, null=True, blank=True, related_name="chiamate",
                               verbose_name="agente")
    strumento = models.CharField("strumento", max_length=60)
    vista = models.CharField("vista", max_length=80, blank=True)
    effetto = models.CharField("effetto", max_length=20)
    esito = models.CharField("esito", max_length=20, choices=ESITI)
    motivo = models.CharField("motivo", max_length=300, blank=True)
    argomenti = models.JSONField("argomenti", default=dict, blank=True)
    anteprima = models.JSONField("anteprima", default=dict, blank=True)
    risultato = models.JSONField("risultato", default=dict, blank=True)
    chiave_idempotenza = models.CharField("chiave di idempotenza", max_length=200, blank=True)

    class Meta:
        verbose_name = "chiamata"
        verbose_name_plural = "chiamate"
        ordering = ["-creato", "-pk"]
        constraints = [models.UniqueConstraint(fields=["chiave_idempotenza"], condition=~Q(chiave_idempotenza=""),
                                               name="awf_chiamata_idempotenza_unica")]

    def __str__(self):
        return f"{self.strumento} ({self.get_esito_display()})"


class RichiestaAgenti(models.Model):
    """Una squadra del catalogo chiesta dal gestionale (§7 del contratto con la fabbrica). Il token della richiesta
    (`wfr_...`) si salva cifrato e serve solo a leggerne lo stato e a ritirarla; quando l'azienda approva il contratto
    in Agate arriva il token della fabbrica e adabox si collega da solo.

    Dalla procedura «Assumi» arrivano anche per chi lavora (reparto, responsabile, persone) e cosa può fare
    (`scelte`: {"strumento|vista": "si" | "ok" | "mai"}). «ok» vale come «si» nelle operazioni ammesse: la conferma
    di una persona la chiederanno le regole di Agate."""
    SI, OK, MAI = "si", "ok", "mai"
    SCELTE = [(SI, "Sì"), (OK, "Con il tuo ok"), (MAI, "Mai")]
    INVIATA, DA_APPROVARE, COLLEGATA, RIFIUTATA, RITIRATA = "inviata", "da_approvare", "collegata", "rifiutata", \
        "ritirata"
    STATI = [(INVIATA, "Inviata"), (DA_APPROVARE, "Contratto da approvare in Agate"), (COLLEGATA, "Collegata"),
             (RIFIUTATA, "Rifiutata"), (RITIRATA, "Ritirata")]
    APERTE = (INVIATA, DA_APPROVARE)
    APPROVATA, IN_CONFERMA, DA_CONFERMARE, RIFIUTATA_QUI, ERRORE = (
        "approvata", "in_conferma", "da_confermare", "rifiutata", "errore")
    DECISIONI = [(APPROVATA, "Approvata in adabox"), (IN_CONFERMA, "Aspetta la doppia conferma"),
                 (DA_CONFERMARE, "Da confermare: diverso da quello confermato"), (RIFIUTATA_QUI, "Rifiutata in adabox"),
                 (ERRORE, "Decisione non arrivata: si riprova")]
    request_id = models.CharField("id della richiesta", max_length=64, unique=True)
    forge_url = models.URLField("indirizzo della fabbrica")
    base_url = models.URLField("indirizzo pubblico dichiarato", blank=True)
    team_slug = models.CharField("squadra", max_length=100)
    team_nome = models.CharField("nome della squadra", max_length=200, blank=True)
    team_versione = models.PositiveIntegerField("versione della squadra", default=1)
    reparto = models.CharField("reparto", max_length=60, blank=True)
    settimane = models.PositiveSmallIntegerField("settimane")
    note = models.TextField("note", blank=True)
    stato = models.CharField("stato", max_length=20, choices=STATI, default=INVIATA)
    messaggio = models.TextField("messaggio della fabbrica", blank=True)
    approve_url = models.URLField("dove approvare in Agate", max_length=500, blank=True)
    token_cifrato = models.TextField("token della richiesta (cifrato)", blank=True, editable=False)
    operazioni = models.JSONField("operazioni chieste dalla squadra", default=list, blank=True)
    prezzo = models.JSONField("prezzo", default=dict, blank=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name="azienda in cui lavoreranno gli agenti")
    creata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", editable=False)
    reparto_azienda = models.CharField("reparto in cui lavora", max_length=80, blank=True)
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="responsabile",
                                     help_text="la persona che segue gli agenti: riepiloghi e approvazioni")
    persone = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="+",
                                     verbose_name="persone a cui passa il lavoro")
    scelte = models.JSONField("cosa può fare", default=dict, blank=True,
                              help_text='{"strumento|vista": "si" | "ok" | "mai"}')
    creata = models.DateTimeField("creata il", auto_now_add=True)
    aggiornata = models.DateTimeField("aggiornata il", auto_now=True)
    letta_il = models.DateTimeField("ultimo stato letto", null=True, blank=True)
    collegata_il = models.DateTimeField("collegata il", null=True, blank=True)
    # il contratto deciso in adabox (§8.4)
    consenso = models.JSONField("cosa ha confermato la persona", default=dict, blank=True,
                                help_text="chi, quando (con la password), squadra e versione, settimane, tetti e prezzo")
    approval_id = models.CharField("approvazione del contratto in Agate", max_length=64, blank=True)
    proposta = models.JSONField("contratto proposto", default=dict, blank=True)
    decisione = models.CharField("decisione del contratto", max_length=20, choices=DECISIONI, blank=True)
    decisione_il = models.DateTimeField("decisione presa il", null=True, blank=True)
    decisione_msg = models.CharField("dettaglio della decisione", max_length=300, blank=True)

    class Meta:
        verbose_name = "richiesta di agenti"
        verbose_name_plural = "richieste di agenti"
        ordering = ["-creata", "-pk"]

    def __str__(self):
        return f"{self.team_nome or self.team_slug} ({self.get_stato_display()})"

    @property
    def aperta(self):
        return self.stato in self.APERTE

    def token(self):
        return cifratura.decifra(self.token_cifrato)
