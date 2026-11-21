import hashlib
import secrets
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.storage import StoragePrivato

# come si vende l'assistente AI: le stesse chiavi che l'istanza legge dalla licenza (ai.licenza)
AI_PROPRIA, AI_INCLUSA, AI_CONSUMO, AI_MISTA = "propria", "inclusa", "consumo", "mista"
FORMULE_AI = [(AI_PROPRIA, "Chiave del cliente"), (AI_INCLUSA, "Inclusa nel canone, con una quota"), (AI_CONSUMO, "A consumo: canone più utilizzo"),
              (AI_MISTA, "Mista: quota inclusa nel canone, poi a consumo")]

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
        help_text="con «inclusa» e «mista» è la quota compresa, con «a consumo» il tetto massimo; 0 = senza "
                  "(con «mista»: la quota per utente per gli utenti)")
    ai_tetto_istanza = models.DecimalField(
        "tetto AI dell'istanza al mese ($)", max_digits=9, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="solo con «mista»: il costo dei modelli oltre il quale l'assistente del piano si ferma; 0 = senza tetto")
    ai_ricarico = models.DecimalField(
        "ricarico sull'AI a consumo (%)", max_digits=6, decimal_places=2, default=0, validators=[MinValueValidator(0)],
        help_text="si aggiunge al costo dei modelli quando l'assistente si fattura a consumo (con «mista»: sulla parte oltre la quota)")
    ai_solo_forniti = models.BooleanField(
        "solo i modelli forniti con il piano", default=False,
        help_text="non con «chiave del cliente»: il cliente non può usare fornitori suoi, risponde solo ciò che forniamo noi")
    acquisto_diretto = models.BooleanField(
        "acquisto diretto dal catalogo", default=False,
        help_text="l'Admin del cliente compra da solo app e suite che hanno un prezzo: entrano subito in licenza e nel canone, "
                  "senza passare dalle Richieste")
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


class ProviderFornito(models.Model):
    """Un fornitore di modelli che diamo ai clienti con la nostra chiave. Le istanze con l'assistente incluso, a
    consumo o misto lo ricevono a ogni sincronizzazione (ai.config_portale) come provider «fornito con il piano», con
    i suoi modelli e i loro prezzi: qui si cambia una volta e vale per tutte, chiave compresa."""
    TIPI = [("anthropic", "Anthropic (Claude)"), ("openai", "OpenAI (GPT)"), ("gemini", "Google (Gemini)"),
            ("mistral", "Mistral AI (La Plateforme)"), ("openai_compat", "Compatibile OpenAI (OpenRouter, Ollama...)")]
    codice = models.SlugField("codice", max_length=40, unique=True, help_text="il nome tecnico con cui le istanze lo riconoscono; non cambiarlo dopo")
    nome = models.CharField("nome", max_length=70, help_text="come lo vedono i clienti")
    tipo = models.CharField("tipo", max_length=15, choices=TIPI)
    base_url = models.URLField("URL dell'API", blank=True, help_text="vuoto = quello predefinito del tipo")
    chiave_cifrata = models.TextField("chiave API (cifrata)", blank=True, editable=False)
    attivo = models.BooleanField("attivo", default=True, help_text="spento, le istanze lo spengono alla prossima sincronizzazione")

    class Meta:
        verbose_name = "provider AI fornito"
        verbose_name_plural = "provider AI forniti"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class ModelloFornito(models.Model):
    """Un modello di un provider fornito, con i prezzi che sulle istanze fanno il costo, le quote e gli importi."""
    provider = models.ForeignKey(ProviderFornito, on_delete=models.CASCADE, related_name="modelli", verbose_name="provider")
    id_api = models.CharField("ID del modello", max_length=120, help_text="es. claude-haiku-5-5")
    etichetta = models.CharField("nome", max_length=80)
    contesto = models.PositiveIntegerField("contesto (token)", default=200000)
    max_output = models.PositiveIntegerField("output massimo (token)", default=8192)
    prezzo_input = models.DecimalField("input $/M token", max_digits=10, decimal_places=4, default=0, validators=[MinValueValidator(0)])
    prezzo_output = models.DecimalField("output $/M token", max_digits=10, decimal_places=4, default=0, validators=[MinValueValidator(0)])
    prezzo_cache_scrittura = models.DecimalField("scrittura cache $/M", max_digits=10, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)])
    prezzo_cache_lettura = models.DecimalField("lettura cache $/M", max_digits=10, decimal_places=4, null=True, blank=True, validators=[MinValueValidator(0)])
    strumenti = models.BooleanField("usa strumenti", default=True)
    visione = models.BooleanField("legge immagini", default=False)
    ragionamento = models.BooleanField("ragiona (effort)", default=False)
    residenza_ue = models.BooleanField("dati in UE", default=False)
    livello_chat = models.CharField("livello in chat", max_length=8, blank=True, choices=[("", "Nessuno"), ("veloce", "Veloce"), ("avanzato", "Avanzato")],
                                    help_text="il modello della scelta «Veloce» o «Avanzato» sulle istanze; «Veloce» fa anche da riserva per i compiti senza un modello utilizzabile")
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "modello AI fornito"
        verbose_name_plural = "modelli AI forniti"
        ordering = ["provider__nome", "etichetta"]
        constraints = [models.UniqueConstraint(fields=["provider", "id_api"], name="rivendita_modello_fornito_unico")]

    def __str__(self):
        return f"{self.etichetta} ({self.provider})"


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
    ai_tetto_istanza = models.DecimalField(
        "tetto AI dell'istanza al mese ($)", max_digits=9, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
        help_text="solo con «mista»; vuoto = quello del piano; 0 = senza tetto")
    ai_ricarico = models.DecimalField(
        "ricarico sull'AI a consumo (%)", max_digits=6, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)],
        help_text="vuoto = quello del piano")
    acquisto_diretto = models.CharField("acquisto diretto dal catalogo", max_length=2, blank=True, choices=[("si", "Sì"), ("no", "No")],
                                        help_text="vuoto = come il piano")
    scadenza = models.DateField("scadenza della licenza")
    grazia_giorni = models.PositiveSmallIntegerField("giorni di grazia", default=30, help_text="dopo la scadenza, prima della sola lettura")
    ospitata = models.BooleanField("ospitata da noi", default=True, help_text="senza accesso del cliente al server")
    attiva = models.BooleanField("attiva", default=True, help_text="spenta, il portale non le risponde più")
    url = models.URLField("indirizzo dell'istanza", blank=True)
    contatto = models.PositiveIntegerField("contatto del cliente (numero)", null=True, blank=True,
                                           help_text="il numero del cliente in Contatti, per le fatture; vuoto = quello con lo stesso nome")
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

    def fa_da_sola(self):
        """Se l'Admin del cliente compra e disdice da solo dal catalogo: lo dice l'istanza o, senza una scelta sua, il piano."""
        scelta = self.acquisto_diretto == "si" if self.acquisto_diretto else self.piano.acquisto_diretto
        return bool(scelta and self.attiva)

    def acquisto_ammesso(self, oggi=None):
        """Comprare, mai a licenza scaduta: lì serve una persona. Disdire si può sempre (fa_da_sola)."""
        return self.fa_da_sola() and self.scadenza >= (oggi or timezone.localdate())

    def termini_ai(self):
        """{formula, quota_utente, quota_istanza, tetto_istanza, ricarico}: i valori dell'istanza, dove ci sono,
        altrimenti del piano. «solo_forniti» è sempre del piano."""
        def scelto(nome):
            proprio = getattr(self, nome)
            return getattr(self.piano, nome) if proprio is None else proprio
        return {"formula": self.ai_formula or self.piano.ai_formula, "quota_utente": scelto("ai_quota_utente"),
                "solo_forniti": self.piano.ai_solo_forniti,
                "quota_istanza": scelto("ai_quota_istanza"), "tetto_istanza": scelto("ai_tetto_istanza"), "ricarico": scelto("ai_ricarico")}


class ChiaveAIIstanza(models.Model):
    """La chiave di un provider fornito per una sola istanza, al posto di quella comune: di norma la chiave virtuale
    creata per quel cliente sul nostro gateway, con il suo indirizzo. Si revoca senza toccare gli altri clienti, e la
    chiave vera non lascia i nostri server. Un'istanza non ospitata da noi riceve un provider solo se ha la sua."""
    provider = models.ForeignKey(ProviderFornito, on_delete=models.CASCADE, related_name="chiavi_istanza", verbose_name="provider")
    istanza = models.ForeignKey(Istanza, on_delete=models.CASCADE, related_name="chiavi_ai", verbose_name="istanza")
    chiave_cifrata = models.TextField("chiave API (cifrata)", editable=False)
    base_url = models.URLField("URL dell'API", blank=True, help_text="l'indirizzo del gateway per questa istanza; vuoto = quello del provider")

    class Meta:
        verbose_name = "chiave AI di un'istanza"
        verbose_name_plural = "chiavi AI delle istanze"
        ordering = ["istanza__cliente", "provider__nome"]
        constraints = [models.UniqueConstraint(fields=["provider", "istanza"], name="rivendita_chiave_ai_istanza_unica")]

    def __str__(self):
        return f"{self.provider} · {self.istanza}"


class Addebito(models.Model):
    """Che cosa c'è da fatturare a un'istanza per un mese: il canone dei giorni in cui ha contato e l'assistente a
    consumo. Lo tiene aggiornato il lavoro pianificato (rivendita.addebiti); chiuso il mese, l'importo non cambia più."""
    APERTO, DA_FATTURARE, FATTURATO, PAGATO, NIENTE = "aperto", "da_fatturare", "fatturato", "pagato", "niente"
    STATI = [(APERTO, "Mese in corso"), (DA_FATTURARE, "Da fatturare"), (FATTURATO, "Fatturato"), (PAGATO, "Pagato"), (NIENTE, "Niente da fatturare")]
    istanza = models.ForeignKey(Istanza, on_delete=models.PROTECT, related_name="addebiti", verbose_name="istanza")
    mese = models.DateField("mese", help_text="il primo giorno")
    piano = models.CharField("piano", max_length=80, blank=True)
    giorni = models.PositiveSmallIntegerField("giorni contati", default=0)
    somma_canoni = models.DecimalField("somma dei canoni giornalieri", max_digits=14, decimal_places=2, default=0, editable=False)
    ultimo_giorno = models.DateField("ultimo giorno contato", null=True, blank=True, editable=False)
    canone = models.DecimalField("canone (€)", max_digits=12, decimal_places=2, default=0)
    ai = models.DecimalField("assistente AI (€)", max_digits=12, decimal_places=2, default=0)
    totale = models.DecimalField("totale (€)", max_digits=12, decimal_places=2, default=0, help_text="senza IVA")
    dettaglio = models.TextField("dettaglio", blank=True)
    stato = models.CharField("stato", max_length=12, choices=STATI, default=APERTO)
    chiuso_il = models.DateTimeField("chiuso il", null=True, blank=True)
    fattura = models.PositiveIntegerField("fattura (numero interno)", null=True, blank=True, help_text="la fattura creata con il modulo Fatturazione")

    class Meta:
        verbose_name = "addebito"
        verbose_name_plural = "addebiti"
        ordering = ["-mese", "istanza__cliente"]
        constraints = [models.UniqueConstraint(fields=["istanza", "mese"], name="rivendita_addebito_unico")]

    def __str__(self):
        return f"{self.istanza} · {self.mese:%m/%Y}"


class Richiesta(models.Model):
    """Un'app chiesta dall'amministratore di un cliente dal suo catalogo, o comprata da lui con l'acquisto diretto
    (`diretto`: nasce già approvata, con il prezzo che ha confermato). Approvata, è anche il contratto di quell'app o
    suite: corre a periodi di 30 giorni da `decisa_il`, e la disdetta del cliente (`disdetta_il`) la fa terminare alla
    `fine` del periodo in corso (rivendita.servizi.disdici, chiudi_disdette)."""
    NUOVA, APPROVATA, RIFIUTATA, TERMINATA = "nuova", "approvata", "rifiutata", "terminata"
    INSTALLAZIONE, DEMO, SUITE = "installazione", "demo", "suite"
    tipo = models.CharField("tipo", max_length=15, choices=[(INSTALLAZIONE, "Installazione"), (DEMO, "Demo"), (SUITE, "Suite")], default=INSTALLAZIONE)
    STATI = [(NUOVA, "Nuova"), (APPROVATA, "Approvata"), (RIFIUTATA, "Rifiutata"), (TERMINATA, "Terminata per disdetta")]
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
    diretto = models.BooleanField("acquisto diretto", default=False, editable=False, help_text="comprato dal cliente dal suo catalogo, senza approvazione")
    prezzo_mese = models.DecimalField("prezzo al mese (€)", max_digits=9, decimal_places=2, null=True, blank=True, editable=False,
                                      help_text="il prezzo confermato dal cliente al momento dell'acquisto")
    disdetta_il = models.DateTimeField("disdetta il", null=True, blank=True, editable=False)
    disdetta_da = models.CharField("disdetta da", max_length=150, blank=True, editable=False)
    fine = models.DateField("termina il", null=True, blank=True, editable=False,
                            help_text="il giorno in cui l'app o la suite esce dalla licenza e dal canone: la fine dei 30 giorni in corso alla disdetta")

    class Meta:
        verbose_name = "richiesta"
        verbose_name_plural = "richieste"
        ordering = ["-creata"]

    def __str__(self):
        return f"{self.nome} per {self.istanza}"


class ConsumoAI(models.Model):
    """Il consumo dell'assistente di un'istanza in un mese, come lo riferisce lei (ai.consumi_portale). Con la formula
    «a consumo» dice che cosa fatturare, con quella «inclusa» quanto margine resta sulla quota, con «mista» tutte e due
    le cose: si fattura solo la parte oltre la quota. Formula e importo sono
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
