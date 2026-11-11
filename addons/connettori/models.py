"""Il ponte con i sistemi esterni: chi avvisare quando cambia un record e a quale record esterno corrisponde."""
import fnmatch
import re
import secrets
import uuid
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from core import cifratura, rete
from core.mixins import AziendaMixin

SCHEMA_EVENTO = re.compile(r"^[a-z0-9_*]+(\.[a-z0-9_*]+){0,2}$")


class Webhook(AziendaMixin):
    """Un indirizzo esterno da avvisare, con la chiave con cui verifica che l'avviso venga da noi."""
    nome = models.CharField("nome", max_length=80)
    url = models.URLField("indirizzo", max_length=500, help_text="Deve iniziare con https://")
    eventi = models.TextField("eventi", help_text="Uno per riga, es. contatti.contatto.creato oppure contatti.contatto.* oppure *")
    attivo = models.BooleanField("attivo", default=True)
    segreto_cifrato = models.TextField(blank=True, editable=False)
    fallimenti_di_fila = models.PositiveIntegerField("fallimenti di fila", default=0, editable=False)
    disattivato_il = models.DateTimeField("disattivato da solo il", null=True, blank=True, editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "webhook"
        verbose_name_plural = "webhook"
        ordering = ["nome", "pk"]

    def __str__(self):
        return self.nome

    def clean(self):
        try:
            rete.controlla(self.url or "", solo_https=True)
        except rete.Rifiutato as e:
            raise ValidationError({"url": f"Indirizzo non valido: {e}."}) from e
        errate = [v for v in self.voci_eventi() if not SCHEMA_EVENTO.match(v)]
        if errate or not self.voci_eventi():
            raise ValidationError({"eventi": f"Eventi non validi: {', '.join(errate)}." if errate else "Indica almeno un evento."})

    def save(self, *args, **kwargs):
        if not self.segreto_cifrato:
            self.nuovo_segreto()
        super().save(*args, **kwargs)

    def nuovo_segreto(self):
        self.segreto_cifrato = cifratura.cifra(secrets.token_urlsafe(32))

    def segreto(self):
        return cifratura.decifra(self.segreto_cifrato)

    def voci_eventi(self):
        return [v.strip() for v in (self.eventi or "").splitlines() if v.strip()]

    def ascolta(self, evento):
        return any(fnmatch.fnmatchcase(evento, v) for v in self.voci_eventi())

    @property
    def host(self):
        return urlsplit(self.url).hostname or ""


class ConsegnaWebhook(models.Model):
    """Un avviso: si legge il record solo al momento di spedire, così più modifiche ravvicinate ne fanno una sola."""
    IN_CODA, CONSEGNATA, FALLITA, SALTATA = "in_coda", "consegnata", "fallita", "saltata"
    STATI = [(IN_CODA, "In coda"), (CONSEGNATA, "Consegnata"), (FALLITA, "Fallita"), (SALTATA, "Saltata")]
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE, related_name="consegne", verbose_name="webhook")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, verbose_name="azienda", editable=False)
    uid = models.UUIDField("identificativo", default=uuid.uuid4, unique=True, editable=False)
    evento = models.CharField("evento", max_length=120, db_index=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="tipo")
    object_id = models.PositiveBigIntegerField("record", null=True, blank=True)
    istantanea = models.JSONField("dati fissati", null=True, blank=True, help_text="per i record eliminati e le prove")
    stato = models.CharField("stato", max_length=12, choices=STATI, default=IN_CODA, db_index=True)
    tentativi = models.PositiveIntegerField("tentativi", default=0)
    risposta = models.PositiveIntegerField("risposta HTTP", null=True, blank=True)
    errore = models.CharField("errore", max_length=300, blank=True)
    creata = models.DateTimeField("creata il", auto_now_add=True)
    consegnata_il = models.DateTimeField("consegnata il", null=True, blank=True)

    class Meta:
        verbose_name = "consegna"
        verbose_name_plural = "consegne"
        ordering = ["-pk"]
        indexes = [models.Index(fields=["webhook", "stato", "evento", "object_id"])]

    def __str__(self):
        return f"{self.evento} · {self.get_stato_display()}"


class RiferimentoEsterno(AziendaMixin):
    """Questo record di adabox corrisponde a quel record del sistema esterno (es. il contatto 123 in HubSpot)."""
    sistema = models.CharField("sistema", max_length=40, help_text="es. hubspot, salesforce, zoho")
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, verbose_name="tipo di record")
    object_id = models.PositiveBigIntegerField("record")
    id_esterno = models.CharField("identificativo esterno", max_length=200)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "collegamento esterno"
        verbose_name_plural = "collegamenti esterni"
        ordering = ["sistema", "pk"]
        indexes = [models.Index(fields=["content_type", "object_id"])]
        constraints = [
            models.UniqueConstraint(fields=["azienda", "sistema", "content_type", "id_esterno"], name="connettori_esterno_unico"),
            models.UniqueConstraint(fields=["azienda", "sistema", "content_type", "object_id"], name="connettori_record_unico"),
        ]

    def __str__(self):
        return f"{self.sistema}: {self.id_esterno}"

    def clean(self):
        if not (self.content_type_id and self.object_id and self.azienda_id):
            return
        modello = self.content_type.model_class()
        if modello is None or not any(f.name == "azienda" for f in modello._meta.fields):
            raise ValidationError({"content_type": "Questo tipo di record non si può collegare."})
        if not modello._default_manager.filter(pk=self.object_id, azienda_id=self.azienda_id).exists():
            raise ValidationError({"object_id": "Il record non esiste in questa azienda."})


class CollegamentoEsterno(AziendaMixin):
    """Il legame di un'azienda con un sistema esterno: quale, con quale token, che cosa passa (persone, aziende,
    opportunità) e chi comanda."""
    HUBSPOT, SALESFORCE, ZOHO, ODOO = "hubspot", "salesforce", "zoho", "odoo"
    SISTEMI = [(HUBSPOT, "HubSpot"), (SALESFORCE, "Salesforce"), (ZOHO, "Zoho CRM"), (ODOO, "Odoo")]
    PROVA, VERA = "prova", "vera"
    MODALITA = [(PROVA, "Prova, senza uscire in rete"), (VERA, "Vera")]
    ESTERNO, ADABOX = "esterno", "adabox"
    COMANDI = [(ESTERNO, "Il sistema esterno: i dati arrivano qui"), (ADABOX, "Adabox: i dati partono da qui")]
    sistema = models.CharField("sistema", max_length=20, choices=SISTEMI, default=HUBSPOT)
    modalita = models.CharField("modalità", max_length=8, choices=MODALITA, default=PROVA)
    comanda = models.CharField("chi comanda", max_length=8, choices=COMANDI, default=ESTERNO)
    attivo = models.BooleanField("attivo", default=True)
    token_cifrato = models.TextField(blank=True, editable=False)          # HubSpot: token dell'app privata; Zoho: refresh token
    indirizzo = models.CharField("indirizzo", max_length=200, blank=True,
                                 help_text="Salesforce: il My Domain (azienda.my.salesforce.com); Zoho: il data center (com, eu, in, com.au, jp, ca, sa)")
    client_id = models.CharField("client id", max_length=200, blank=True, help_text="Salesforce e Zoho: l'identificativo dell'app")
    database = models.CharField("database", max_length=80, blank=True, help_text="Odoo: il nome del database (se l'indirizzo ne serve più d'uno)")
    per_utente = models.BooleanField("ogni utente con la sua chiave", default=False,
                                     help_text="Odoo: ogni utente collega il suo account e vede in adabox solo ciò che quel sistema mostra a lui")
    segreto_cifrato = models.TextField(blank=True, editable=False)        # Salesforce e Zoho: il client secret
    accesso_cifrato = models.TextField(blank=True, editable=False)        # il token di accesso del momento, condiviso tra i lavori
    accesso_scade = models.DateTimeField(null=True, blank=True, editable=False)
    aziende = models.BooleanField("anche le aziende", default=True,
                                  help_text="le aziende (companies) con le persone che ci lavorano")
    opportunita = models.BooleanField("anche le opportunità", default=True,
                                      help_text="le opportunità (deals) con fase, valore e chiusura prevista; serve il CRM")
    cursore = models.DateTimeField("letto fino a", null=True, blank=True, editable=False)
    cursori = models.JSONField("letto fino a, per tipo", default=dict, blank=True, editable=False)
    ultimo_giro = models.DateTimeField("ultimo giro", null=True, blank=True, editable=False)
    ultimo_esito = models.CharField("ultimo esito", max_length=500, blank=True, editable=False)
    in_errore = models.BooleanField("in errore", default=False, editable=False)

    class Meta(AziendaMixin.Meta):
        verbose_name = "collegamento"
        verbose_name_plural = "collegamenti"
        ordering = ["sistema", "pk"]
        constraints = [models.UniqueConstraint(fields=["azienda", "sistema"], name="connettori_un_collegamento_per_sistema")]
        permissions = [("vede_tutti_i_dati_esterni", "Vede anche i dati esterni che il sistema mostra ad altri utenti")]

    def __str__(self):
        return f"{self.get_sistema_display()} ({self.get_modalita_display().split(',')[0].lower()})"

    def token(self):
        return cifratura.decifra(self.token_cifrato)

    def segreto(self):
        return cifratura.decifra(self.segreto_cifrato)


class AccountEsterno(models.Model):
    """L'account di un utente su un sistema esterno (collegamento «ogni utente con la sua chiave»): i dati arrivano con
    la sua chiave, quindi con i suoi permessi in quel sistema, e in adabox li vede lui (VisibilitaEsterna)."""
    collegamento = models.ForeignKey(CollegamentoEsterno, on_delete=models.CASCADE, related_name="account", verbose_name="collegamento")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="account_esterni", verbose_name="utente")
    chiave_cifrata = models.TextField(blank=True, editable=False)
    id_utente_esterno = models.CharField("utente nel sistema", max_length=64, blank=True, editable=False)
    cursori = models.JSONField("letto fino a, per tipo", default=dict, blank=True, editable=False)
    ultimo_giro = models.DateTimeField("ultimo giro", null=True, blank=True, editable=False)
    ultimo_esito = models.CharField("ultimo esito", max_length=500, blank=True, editable=False)
    in_errore = models.BooleanField("da ricollegare", default=False, editable=False)
    creato = models.DateTimeField("collegato il", auto_now_add=True)

    class Meta:
        verbose_name = "account esterno"
        verbose_name_plural = "account esterni"
        ordering = ["collegamento", "utente"]
        constraints = [models.UniqueConstraint(fields=["collegamento", "utente"], name="connettori_un_account_per_utente")]

    def __str__(self):
        return f"{self.utente} su {self.collegamento.get_sistema_display()}"

    def chiave(self):
        return cifratura.decifra(self.chiave_cifrata)


class VisibilitaEsterna(models.Model):
    """Questo account vede questo record nel sistema esterno: in adabox il record arrivato da lì lo vede chi ce l'ha."""
    riferimento = models.ForeignKey(RiferimentoEsterno, on_delete=models.CASCADE, related_name="visibilita")
    account = models.ForeignKey(AccountEsterno, on_delete=models.CASCADE, related_name="visibili")

    class Meta:
        verbose_name = "visibilità esterna"
        verbose_name_plural = "visibilità esterne"
        constraints = [models.UniqueConstraint(fields=["riferimento", "account"], name="connettori_visibilita_unica")]


class RecordProva(models.Model):
    """Un record del sistema esterno finto: fa le veci di HubSpot, Salesforce o Zoho quando il collegamento è in prova,
    con i nomi dei campi di quel sistema."""
    collegamento = models.ForeignKey(CollegamentoEsterno, on_delete=models.CASCADE, related_name="record_prova")
    tipo = models.CharField(max_length=20, default="contacts")
    id_esterno = models.CharField(max_length=40)
    proprieta = models.JSONField(default=dict)
    associazioni = models.JSONField(default=dict)           # {"companies": ["12"], ...}
    modificato_ms = models.BigIntegerField(default=0, db_index=True)

    class Meta:
        verbose_name = "record di prova"
        verbose_name_plural = "record di prova"
        ordering = ["-modificato_ms", "pk"]
        constraints = [models.UniqueConstraint(fields=["collegamento", "tipo", "id_esterno"], name="connettori_record_prova_unico_tipo")]
