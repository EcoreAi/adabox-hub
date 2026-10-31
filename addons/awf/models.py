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
    ultimo_stato = models.JSONField("ultimo stato dell'ingaggio", default=dict, blank=True)
    stato_il = models.DateTimeField("ultimo battito riuscito", null=True, blank=True)
    ultimo_errore = models.CharField("ultimo errore", max_length=300, blank=True)
    collegato_il = models.DateTimeField("collegato il", null=True, blank=True)
    azienda = models.ForeignKey(Azienda, on_delete=models.SET_NULL, null=True, blank=True,
                                verbose_name="azienda in cui lavorano gli agenti")
    agate_url = models.URLField("indirizzo della console di Agate", blank=True,
                                help_text="vuoto = quello indicato dalla fabbrica")

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
    """Un agente dell'ingaggio, con il suo utente Django (`awf-<nome>`): attivo, senza password usabile, senza
    email, mai nell'interfaccia. Agisce solo nelle chiamate MCP che Agate ha già deciso."""
    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agente_awf",
                                  verbose_name="utente")
    nome = models.CharField("nome", max_length=100)
    ruolo = models.CharField("ruolo", max_length=100, blank=True)
    agate_agent_id = models.CharField("id in Agate", max_length=100, blank=True, db_index=True)
    attivo = models.BooleanField("nell'ingaggio", default=True,
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
    Qui si mostra e basta: si decide solo nella console di Agate."""
    IN_ATTESA = "in_attesa"
    approval_id = models.CharField("id in Agate", max_length=64, unique=True)
    strumento = models.CharField("strumento", max_length=200, blank=True)
    riepilogo = models.TextField("riepilogo", blank=True, help_text="già mascherato da Agate")
    scade = models.DateTimeField("scade il", null=True, blank=True)
    stato = models.CharField("stato", max_length=20, default=IN_ATTESA)
    ricevuta = models.DateTimeField("ricevuta il", auto_now_add=True)
    decisa = models.DateTimeField("decisa il", null=True, blank=True)

    class Meta:
        verbose_name = "approvazione"
        verbose_name_plural = "approvazioni"
        ordering = ["-ricevuta"]

    def __str__(self):
        return self.riepilogo[:80] or self.approval_id


class Chiamata(models.Model):
    """Registro delle chiamate degli agenti. Delle scritture tiene argomenti, anteprima ed esito (anche quelle
    ferme in osservazione: «cosa sarebbe successo»); delle letture solo strumento, vista ed esito."""
    ESEGUITA, OSSERVAZIONE, RIFIUTATA, ERRORE = "eseguita", "osservazione", "rifiutata", "errore"
    ESITI = [(ESEGUITA, "Eseguita"), (OSSERVAZIONE, "In osservazione (non eseguita)"), (RIFIUTATA, "Rifiutata"),
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
