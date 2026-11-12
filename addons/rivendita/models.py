import hashlib
import secrets
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.storage import StoragePrivato

# come si vende l'assistente AI: le stesse chiavi che l'istanza legge dalla licenza (ai.licenza)
AI_PROPRIA, AI_INCLUSA, AI_CONSUMO = "propria", "inclusa", "consumo"
FORMULE_AI = [(AI_PROPRIA, "Chiave del cliente"), (AI_INCLUSA, "Inclusa nel canone, con una quota"), (AI_CONSUMO, "A consumo: canone più utilizzo")]

class ModuloVendibile(models.Model):
    """Un modulo del catalogo commerciale: nasce pubblicando il suo primo pacchetto."""
    slug = models.SlugField("slug", max_length=31, unique=True)
    nome = models.CharField("nome", max_length=120)
    riassunto = models.CharField("riassunto", max_length=300, blank=True)
    categoria = models.CharField("categoria", max_length=60, blank=True)
    application = models.BooleanField("è un'app", default=True, help_text="i moduli di servizio (es. dati fiscali) non compaiono nel catalogo del cliente")
    icona = models.TextField("icona", blank=True, editable=False)
    prezzo_mese = models.DecimalField("prezzo al mese (€)", max_digits=9, decimal_places=2, default=0)
    in_catalogo = models.BooleanField("visibile nel catalogo dei clienti", default=True)
    su_misura = models.BooleanField("su misura", default=False, help_text="di un cliente: mai nel catalogo degli altri né in un piano; lo ricevono solo le istanze che lo hanno tra i moduli in più")
    descrizione = models.TextField("che cosa fa", blank=True, help_text="il testo della finestra «Informazioni» nel catalogo del cliente")
    funzioni = models.TextField("funzioni", blank=True, help_text="una per riga")
    url_demo = models.URLField("link alla demo", blank=True, help_text="vuoto = quello generale, RIVENDITA_URL_DEMO")

    class Meta:
        verbose_name = "modulo in vendita"
        verbose_name_plural = "moduli in vendita"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def ultimo(self):
        """Il pacchetto pubblicato più recente."""
        from core.registry.manifest import versione_tupla
        pacchetti = list(self.pacchetti.filter(pubblicato=True))
        return max(pacchetti, key=lambda p: versione_tupla(p.versione), default=None)


class FunzioneVendibile(models.Model):
    """Una funzione attivabile di un modulo (core.funzioni), dal manifest del suo ultimo pacchetto: il piano e l'istanza
    scelgono quali comprendere, e vanno in licenza."""
    modulo = models.ForeignKey(ModuloVendibile, on_delete=models.CASCADE, related_name="funzioni_attivabili", verbose_name="modulo")
    chiave = models.CharField("chiave", max_length=40)
    nome = models.CharField("nome", max_length=120)
    spiegazione = models.CharField("spiegazione", max_length=300, blank=True)
    ordine = models.PositiveSmallIntegerField("ordine", default=0)

    class Meta:
        verbose_name = "funzione attivabile"
        verbose_name_plural = "funzioni attivabili"
        ordering = ["modulo__nome", "ordine"]
        constraints = [models.UniqueConstraint(fields=["modulo", "chiave"], name="rivendita_funzione_unica")]

    def __str__(self):
        return f"{self.modulo.nome} · {self.nome}"


class Pacchetto(models.Model):
    """Una versione di un modulo: lo zip firmato che le istanze licenziate scaricano."""
    modulo = models.ForeignKey(ModuloVendibile, on_delete=models.CASCADE, related_name="pacchetti", verbose_name="modulo")
    versione = models.CharField("versione", max_length=20)
    min_core = models.CharField("kernel minimo", max_length=20, blank=True)
    dipendenze = models.JSONField("dipendenze", default=list, blank=True)
    file = models.FileField("file", upload_to="rivendita/pacchetti/", storage=StoragePrivato(), max_length=300)
    nome_file = models.CharField("nome del file", max_length=120)
    sha256 = models.CharField("SHA-256", max_length=64)
    dimensione = models.PositiveIntegerField("dimensione (byte)", default=0)
    pubblicato = models.BooleanField("pubblicato", default=True, help_text="spento, le istanze non lo ricevono più")
    creato = models.DateTimeField("caricato il", auto_now_add=True)

    class Meta:
        verbose_name = "pacchetto"
        verbose_name_plural = "pacchetti"
        ordering = ["-creato"]
        constraints = [models.UniqueConstraint(fields=["modulo", "versione"], name="rivendita_pacchetto_unico")]

    def __str__(self):
        return self.nome_file


class Piano(models.Model):
    """Il prezzo base con le sue app."""
    nome = models.CharField("nome", max_length=80, unique=True)
    descrizione = models.TextField("descrizione", blank=True)
    moduli = models.ManyToManyField(ModuloVendibile, blank=True, limit_choices_to={"su_misura": False}, related_name="piani", verbose_name="moduli inclusi")
    utenti = models.PositiveIntegerField("utenti inclusi", default=0, help_text="0 = senza tetto")
    prezzo_mese = models.DecimalField("prezzo al mese (€)", max_digits=9, decimal_places=2, default=0)
    prezzo_utente_mese = models.DecimalField(
        "prezzo per utente al mese (€)", max_digits=9, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="abbonamento per utente: si moltiplica per gli utenti dell'istanza e si somma al prezzo al mese")
    ai_formula = models.CharField("assistente AI", max_length=8, choices=FORMULE_AI, default=AI_PROPRIA,
                                  help_text="con «inclusa» e «a consumo» i modelli li fornisce chi vende, con la sua chiave")
    ai_quota_utente = models.DecimalField(
        "quota AI per utente al mese ($)", max_digits=9, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="con «inclusa»: costo dei modelli compreso per ogni utente; 0 = senza quota")
    ai_quota_istanza = models.DecimalField(
        "quota AI dell'istanza al mese ($)", max_digits=9, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="con «inclusa» è la quota compresa, con «a consumo» il tetto massimo; 0 = senza")
    ai_ricarico = models.DecimalField(
        "ricarico sull'AI a consumo (%)", max_digits=6, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="si aggiunge al costo dei modelli quando l'assistente si fattura a consumo")
    attivo = models.BooleanField("attivo", default=True)
    moduli_a_funzioni = models.ManyToManyField(
        ModuloVendibile, blank=True, related_name="piani_a_funzioni", verbose_name="moduli con le funzioni scelte",
        help_text="di questi moduli il piano comprende solo le funzioni scelte qui sotto (anche nessuna); gli altri le hanno tutte")
    funzioni = models.ManyToManyField(FunzioneVendibile, blank=True, related_name="piani", verbose_name="funzioni comprese")

    class Meta:
        verbose_name = "piano"
        verbose_name_plural = "piani"
        ordering = ["prezzo_mese", "nome"]

    def __str__(self):
        return self.nome


class Suite(models.Model):
    """Un pacchetto di app per dipartimento (Marketing, Vendite…), venduto accanto al piano base. Sull'istanza fa nascere
    un dipartimento con le sue app, che lo segue; con un tetto, le persone che vedono le sue app non lo superano."""
    nome = models.CharField("nome", max_length=80, unique=True)
    slug = models.SlugField("slug", max_length=31, unique=True, help_text="il nome tecnico che va in licenza; non cambiarlo dopo la vendita")
    descrizione = models.TextField("che cosa offre", blank=True, help_text="il testo del catalogo del cliente")
    moduli = models.ManyToManyField(ModuloVendibile, blank=True, limit_choices_to={"su_misura": False}, related_name="suite", verbose_name="app incluse")
    utenti = models.PositiveIntegerField("persone incluse", default=0, help_text="quante persone possono usarne le app; 0 = senza tetto")
    prezzo_mese = models.DecimalField("prezzo al mese (€)", max_digits=9, decimal_places=2, default=0)
    in_catalogo = models.BooleanField("visibile nel catalogo dei clienti", default=True)
    ordine = models.PositiveSmallIntegerField("ordine", default=10)

    class Meta:
        verbose_name = "suite"
        verbose_name_plural = "suite"
        ordering = ["ordine", "nome"]

    def __str__(self):
        return self.nome


def _impronta(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Istanza(models.Model):
    """L'installazione di un cliente. Il token si vede una volta sola: qui resta solo la sua impronta."""
    cliente = models.CharField("cliente", max_length=200)
    email = models.EmailField("email di riferimento", blank=True)
    codice = models.UUIDField("codice", default=uuid.uuid4, unique=True, editable=False)
    token_hash = models.CharField("impronta del token", max_length=64, blank=True, editable=False, db_index=True)
    piano = models.ForeignKey(Piano, on_delete=models.PROTECT, related_name="istanze", verbose_name="piano")
    moduli_extra = models.ManyToManyField(ModuloVendibile, blank=True, related_name="istanze_extra", verbose_name="moduli in più")
    suite = models.ManyToManyField(Suite, blank=True, related_name="istanze", verbose_name="suite comprate")
    funzioni_extra = models.ManyToManyField(FunzioneVendibile, blank=True, related_name="istanze", verbose_name="funzioni in più",
                                            help_text="oltre a quelle del piano, per i moduli con le funzioni scelte")
    utenti = models.PositiveIntegerField("utenti", null=True, blank=True, help_text="vuoto = quelli del piano; 0 = senza tetto")
    ai_formula = models.CharField("assistente AI", max_length=8, choices=FORMULE_AI, blank=True, help_text="vuoto = come il piano")
    ai_quota_utente = models.DecimalField(
        "quota AI per utente al mese ($)", max_digits=9, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
        help_text="vuoto = quella del piano; 0 = senza quota")
    ai_quota_istanza = models.DecimalField(
        "quota AI dell'istanza al mese ($)", max_digits=9, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
        help_text="vuoto = quella del piano; 0 = senza")
    ai_ricarico = models.DecimalField(
        "ricarico sull'AI a consumo (%)", max_digits=6, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
        help_text="vuoto = quello del piano")
    scadenza = models.DateField("scadenza della licenza")
    grazia_giorni = models.PositiveSmallIntegerField("giorni di grazia", default=30, help_text="dopo la scadenza, prima della sola lettura")
    ospitata = models.BooleanField("ospitata da noi", default=True, help_text="senza accesso del cliente al server")
    attiva = models.BooleanField("attiva", default=True, help_text="spenta, il portale non le risponde più")
    url = models.URLField("indirizzo dell'istanza", blank=True)
    note = models.TextField("note", blank=True)
    ultimo_contatto = models.DateTimeField("ultimo contatto", null=True, blank=True, editable=False)
    moduli_presenti = models.JSONField("moduli presenti", default=dict, blank=True, editable=False)
    utenti_attivi = models.PositiveIntegerField("utenti attivi", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "istanza"
        verbose_name_plural = "istanze"
        ordering = ["cliente"]

    def __str__(self):
        return self.cliente

    def nuovo_token(self):
        token = secrets.token_urlsafe(32)
        self.token_hash = _impronta(token)
        self.save(update_fields=["token_hash"])
        return token

    @classmethod
    def per_token(cls, token):
        return cls.objects.select_related("piano").filter(token_hash=_impronta(token), attiva=True).first() if token else None

    def registra_contatto(self, moduli, utenti_attivi):
        self.ultimo_contatto, self.moduli_presenti, self.utenti_attivi = timezone.now(), moduli, utenti_attivi
        self.save(update_fields=["ultimo_contatto", "moduli_presenti", "utenti_attivi"])

    def posti(self):
        """Gli utenti che si fatturano: quelli della licenza o, senza tetto, quelli attivi riferiti dall'istanza."""
        utenti = self.utenti if self.utenti is not None else self.piano.utenti
        return utenti or self.utenti_attivi or 0

    def canone_mese(self):
        """Il canone in euro senza l'utilizzo dell'AI: piano, prezzo per utente, suite e moduli in più."""
        return (self.piano.prezzo_mese + self.piano.prezzo_utente_mese * self.posti()
                + sum(su.prezzo_mese for su in self.suite.all()) + sum(m.prezzo_mese for m in self.moduli_extra.all()))

    def termini_ai(self):
        """{formula, quota_utente, quota_istanza, ricarico}: i valori dell'istanza, dove ci sono, altrimenti del piano."""
        def scelto(nome):
            proprio = getattr(self, nome)
            return getattr(self.piano, nome) if proprio is None else proprio
        return {"formula": self.ai_formula or self.piano.ai_formula, "quota_utente": scelto("ai_quota_utente"),
                "quota_istanza": scelto("ai_quota_istanza"), "ricarico": scelto("ai_ricarico")}


class Richiesta(models.Model):
    """Un'app chiesta dall'amministratore di un cliente dal suo catalogo."""
    NUOVA, APPROVATA, RIFIUTATA = "nuova", "approvata", "rifiutata"
    INSTALLAZIONE, DEMO, SUITE = "installazione", "demo", "suite"
    tipo = models.CharField("tipo", max_length=15, choices=[(INSTALLAZIONE, "Installazione"), (DEMO, "Demo"), (SUITE, "Suite")], default=INSTALLAZIONE)
    STATI = [(NUOVA, "Nuova"), (APPROVATA, "Approvata"), (RIFIUTATA, "Rifiutata")]
    istanza = models.ForeignKey(Istanza, on_delete=models.CASCADE, related_name="richieste", verbose_name="istanza")
    slug = models.SlugField("modulo", max_length=31)
    nome = models.CharField("nome", max_length=120)
    nota = models.TextField("nota", blank=True)
    utente = models.CharField("chiesta da", max_length=150, blank=True)
    id_remoto = models.PositiveBigIntegerField("id sull'istanza", null=True, blank=True, editable=False)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=NUOVA, editable=False)
    creata = models.DateTimeField("chiesta il", auto_now_add=True)
    decisa_il = models.DateTimeField("decisa il", null=True, blank=True, editable=False)
    decisa_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", editable=False, verbose_name="decisa da")

    class Meta:
        verbose_name = "richiesta"
        verbose_name_plural = "richieste"
        ordering = ["-creata"]

    def __str__(self):
        return f"{self.nome} per {self.istanza}"


class ConsumoAI(models.Model):
    """Il consumo dell'assistente di un'istanza in un mese, come lo riferisce lei (ai.consumi_portale). Con la formula
    «a consumo» dice che cosa fatturare, con quella «inclusa» quanto margine resta sulla quota. Formula e importo sono
    quelli dell'ultimo aggiornamento: l'istanza rimanda il mese fino alla fine di quello dopo, poi la riga resta ferma."""
    istanza = models.ForeignKey(Istanza, on_delete=models.CASCADE, related_name="consumi_ai", verbose_name="istanza")
    mese = models.DateField("mese", help_text="il primo giorno")
    costo = models.DecimalField("costo dei modelli ($)", max_digits=12, decimal_places=4, default=0)
    costo_fornito = models.DecimalField("di cui sul piano ($)", max_digits=12, decimal_places=4, default=0,
                                        help_text="sui provider forniti con il piano: il resto è su chiavi del cliente o modelli locali")
    turni = models.PositiveIntegerField("turni", default=0)
    utenti = models.PositiveIntegerField("persone in chat", default=0)
    formula = models.CharField("formula", max_length=8, choices=FORMULE_AI, default=AI_PROPRIA)
    quota = models.DecimalField("quota del mese ($)", max_digits=12, decimal_places=2, default=0, help_text="0 = senza")
    importo = models.DecimalField("da fatturare (€)", max_digits=12, decimal_places=2, default=0)
    aggiornato = models.DateTimeField("aggiornato il", auto_now=True)

    class Meta:
        verbose_name = "consumo AI"
        verbose_name_plural = "consumi AI"
        ordering = ["-mese", "istanza__cliente"]
        constraints = [models.UniqueConstraint(fields=["istanza", "mese"], name="rivendita_consumo_ai_unico")]

    def __str__(self):
        return f"{self.istanza} · {self.mese:%m/%Y}"
