"""Collegamento ad Agate e valutazioni delle proposte dell'assistente.

Il collegamento è uno solo per istanza: indirizzo del gateway e della console di Agate, la chiave
(scope `evaluate` e `llm`) e il segreto dei webhook, cifrati come le chiavi dei provider. La
modalità decide quanto conta Agate: spenta, in prova (Agate valuta e registra soltanto, adabox esegue
comunque) o attiva (decide Agate). I valori salvati restano spento, osservazione e attivo.

Collegato con un codice (§8.1 di plugin-api.md) ci sono anche la chiave `decide` (solo approve: le decisioni delle
persone, prese in adabox) e la chiave `sync` (solo app: risincronizzare gli strumenti), cifrate come l'altra."""
from django.conf import settings
from django.db import models

from core import cifratura


class Collegamento(models.Model):
    SPENTO, OSSERVAZIONE, ATTIVO = "spento", "osservazione", "attivo"
    MODALITA = [(SPENTO, "Spenta"), (OSSERVAZIONE, "In prova (registra soltanto)"), (ATTIVO, "Attiva")]
    SPIEGAZIONI = {SPENTO: "Agate non viene chiamato: l'assistente fa come prima.",
                   OSSERVAZIONE: "Agate valuta e registra ogni modifica, ma adabox la esegue comunque: per vedere "
                                 "cosa cambierebbe prima di accendere.",
                   ATTIVO: "Decide Agate: consente, chiede l'ok di una persona o blocca. Se Agate non risponde, non si "
                           "esegue nulla."}
    gateway_url = models.URLField("gateway di Agate", help_text="es. https://api.agate.esempio.it")
    console_url = models.URLField("console di Agate", blank=True, help_text="per i link a chi approva")
    chiave_cifrata = models.TextField("chiave API (cifrata)", blank=True, editable=False)
    segreto_cifrato = models.TextField("segreto dei webhook (cifrato)", blank=True, editable=False)
    prefisso = models.SlugField("prefisso degli strumenti in Agate", max_length=30, default="adabox",
                                help_text="gli strumenti dell'assistente in Agate si chiamano <prefisso>.<nome>")
    modalita = models.CharField("modalità", max_length=12, choices=MODALITA, default=OSSERVAZIONE)
    ultimo_controllo = models.DateTimeField("ultimo controllo", null=True, blank=True)
    esito_controllo = models.CharField("esito del controllo", max_length=300, blank=True)
    # il percorso semplice (§8.1): adabox collegato una volta sola con un codice agc_
    chiave_decide_cifrata = models.TextField("chiave per le decisioni (cifrata)", blank=True, editable=False)
    chiave_sync_cifrata = models.TextField("chiave per risincronizzare gli strumenti (cifrata)", blank=True,
                                           editable=False)
    tenant = models.CharField("azienda in Agate", max_length=200, blank=True)
    con_codice_il = models.DateTimeField("collegato con un codice il", null=True, blank=True)
    da_sincronizzare = models.BooleanField("strumenti da risincronizzare", default=False,
                                           help_text="l'ultima risincronizzazione non è riuscita: si riprova da sola")
    sincronizzato_il = models.DateTimeField("ultima risincronizzazione", null=True, blank=True)
    esito_sincronizzazione = models.CharField("esito della risincronizzazione", max_length=300, blank=True)

    class Meta:
        verbose_name = "collegamento ad Agate"
        verbose_name_plural = "collegamento ad Agate"

    def __str__(self):
        return self.gateway_url

    @classmethod
    def attuale(cls):
        return cls.objects.order_by("pk").first()

    def chiave(self):
        return cifratura.decifra(self.chiave_cifrata)

    def imposta_chiave(self, chiave):
        self.chiave_cifrata = cifratura.cifra(chiave)

    def segreto(self):
        return cifratura.decifra(self.segreto_cifrato)

    def imposta_segreto(self, segreto):
        self.segreto_cifrato = cifratura.cifra(segreto)

    def chiave_decide(self):
        return cifratura.decifra(self.chiave_decide_cifrata)

    def chiave_sync(self):
        return cifratura.decifra(self.chiave_sync_cifrata)

    @property
    def puo_decidere(self):
        """Collegato con il codice: le decisioni si prendono in adabox, a nome di chi clicca."""
        return bool(self.chiave_decide_cifrata)

    def strumento(self, nome):
        return f"{self.prefisso}.{nome}"


class Valutazione(models.Model):
    """Quello che Agate ha detto di una proposta dell'assistente, e cosa ne è stato."""
    CONSENTITA, IN_ATTESA, APPROVATA, RIFIUTATA, NEGATA, OSSERVATA, ERRORE = (
        "consentita", "in_attesa", "approvata", "rifiutata", "negata", "osservata", "errore")
    STATI = [(CONSENTITA, "Consentita"), (IN_ATTESA, "In attesa di approvazione"), (APPROVATA, "Approvata"),
             (RIFIUTATA, "Rifiutata o scaduta"), (NEGATA, "Bloccata dalle regole"),
             (OSSERVATA, "Solo registrata (in prova)"), (ERRORE, "Agate non raggiungibile")]
    proposta = models.OneToOneField("ai.Proposta", on_delete=models.CASCADE, related_name="agate",
                                    verbose_name="proposta")
    strumento = models.CharField("strumento in Agate", max_length=100)
    evaluation_id = models.CharField("valutazione", max_length=40, blank=True, db_index=True)
    verdetto = models.CharField("verdetto", max_length=20, blank=True)
    approval_id = models.CharField("approvazione", max_length=40, blank=True, db_index=True)
    stato = models.CharField("stato", max_length=10, choices=STATI)
    motivo = models.TextField("motivo", blank=True)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+",
                               verbose_name="chi ha confermato")
    creata = models.DateTimeField("creata il", auto_now_add=True)
    decisa = models.DateTimeField("decisa il", null=True, blank=True)

    class Meta:
        verbose_name = "valutazione di Agate"
        verbose_name_plural = "valutazioni di Agate"
        ordering = ["-creata"]

    def __str__(self):
        return f"{self.strumento}: {self.get_stato_display()}"
