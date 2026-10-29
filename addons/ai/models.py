from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Conversazione(models.Model):
    """Una chat con l'assistente: personale, la vede solo chi l'ha aperta."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversazioni",
                               verbose_name="utente")
    titolo = models.CharField("titolo", max_length=120, default="Nuova chat")
    ambito = models.CharField("limitata all'app", max_length=31, blank=True,
                              help_text="slug dell'app a cui la chat è limitata; vuoto = tutte")
    preferita = models.BooleanField("preferita", default=False)
    titolo_generato = models.BooleanField("titolo scritto dall'assistente", default=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)
    aggiornata = models.DateTimeField("aggiornata il", auto_now=True)

    class Meta:
        verbose_name = "conversazione"
        verbose_name_plural = "conversazioni"
        ordering = ["-aggiornata", "-pk"]

    def __str__(self):
        return self.titolo


class MessaggioChat(models.Model):
    UTENTE, ASSISTENTE = "utente", "assistente"
    conversazione = models.ForeignKey(Conversazione, on_delete=models.CASCADE, related_name="messaggi",
                                      verbose_name="conversazione")
    ruolo = models.CharField("ruolo", max_length=10, choices=[(UTENTE, "Utente"), (ASSISTENTE, "Assistente")])
    testo = models.TextField("testo")
    turno = models.ForeignKey("Turno", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                              verbose_name="turno")
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta:
        verbose_name = "messaggio"
        verbose_name_plural = "messaggi"
        ordering = ["creato", "pk"]

    def __str__(self):
        return f"{self.get_ruolo_display()}: {self.testo[:40]}"


class Provider(models.Model):
    """Un fornitore di modelli: API Anthropic, endpoint compatibile OpenAI (OpenAI, OpenRouter, Ollama, vLLM,
    Gemini) o il modello finto per test e demo. La chiave API è cifrata; le aziende possono avere la propria."""
    ANTHROPIC, OPENAI_COMPAT, FINTO = "anthropic", "openai_compat", "finto"
    TIPI = [(ANTHROPIC, "Anthropic (Claude)"), (OPENAI_COMPAT, "Compatibile OpenAI (OpenAI, OpenRouter, Ollama...)"),
            (FINTO, "Finto (test e demo)")]
    nome = models.CharField("nome", max_length=80, unique=True)
    tipo = models.CharField("tipo", max_length=15, choices=TIPI)
    base_url = models.URLField("URL dell'API", blank=True, help_text="vuoto = quello predefinito del tipo")
    chiave_cifrata = models.TextField("chiave API (cifrata)", blank=True, editable=False)
    locale = models.BooleanField("locale", default=False, help_text="gira sui nostri server: i dati non escono")
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "provider"
        verbose_name_plural = "provider"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def chiave_per(self, azienda=None):
        """La chiave dell'azienda se c'è, altrimenti quella globale (in chiaro, solo in memoria)."""
        from core import cifratura
        if azienda is not None:
            propria = self.chiavi_azienda.filter(azienda=azienda).first()
            if propria and propria.chiave_cifrata:
                return cifratura.decifra(propria.chiave_cifrata)
        return cifratura.decifra(self.chiave_cifrata)


class ChiaveAzienda(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="chiavi_azienda",
                                 verbose_name="provider")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, verbose_name="azienda")
    chiave_cifrata = models.TextField("chiave API (cifrata)", editable=False)

    class Meta:
        verbose_name = "chiave API dell'azienda"
        verbose_name_plural = "chiavi API delle aziende"
        constraints = [models.UniqueConstraint(fields=["provider", "azienda"], name="ai_chiave_azienda_unica")]

    def __str__(self):
        return f"{self.provider} · {self.azienda}"


class Modello(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="modelli", verbose_name="provider")
    id_api = models.CharField("ID del modello", max_length=120, help_text="es. claude-haiku-5-5")
    etichetta = models.CharField("nome", max_length=80)
    contesto = models.PositiveIntegerField("contesto (token)", default=200000)
    max_output = models.PositiveIntegerField("output massimo (token)", default=8192)
    prezzo_input = models.DecimalField("input $/M token", max_digits=10, decimal_places=4, null=True, blank=True)
    prezzo_output = models.DecimalField("output $/M token", max_digits=10, decimal_places=4, null=True, blank=True)
    prezzo_cache_scrittura = models.DecimalField("scrittura cache $/M", max_digits=10, decimal_places=4, null=True,
                                                 blank=True)
    prezzo_cache_lettura = models.DecimalField("lettura cache $/M", max_digits=10, decimal_places=4, null=True,
                                               blank=True)
    strumenti = models.BooleanField("usa strumenti", default=True)
    visione = models.BooleanField("legge immagini", default=False)
    ragionamento = models.BooleanField("ragiona (effort)", default=False)
    residenza_ue = models.BooleanField("dati in UE", default=False)
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "modello"
        verbose_name_plural = "modelli"
        ordering = ["provider__nome", "etichetta"]
        constraints = [models.UniqueConstraint(fields=["provider", "id_api"], name="ai_modello_unico")]

    def __str__(self):
        return f"{self.etichetta} ({self.provider})"

    def costo(self, uso):
        """Costo in dollari di un uso {input, output, cache_scrittura, cache_lettura} (token)."""
        from decimal import Decimal
        milione = Decimal(1_000_000)
        voci = [(uso.get("input", 0), self.prezzo_input), (uso.get("output", 0), self.prezzo_output),
                (uso.get("cache_scrittura", 0), self.prezzo_cache_scrittura or self.prezzo_input),
                (uso.get("cache_lettura", 0), self.prezzo_cache_lettura or self.prezzo_input)]
        return sum((Decimal(n) * (p or 0) / milione for n, p in voci), Decimal(0))


class Profilo(models.Model):
    """Quale catena di modelli usare per un compito, per tutti o per un'app o un'azienda."""
    COMPITI = [("chat", "Chat e agente"), ("titoli", "Titoli delle chat"), ("riassunti", "Riassunti"),
               ("pianificate", "Attività pianificate"), ("classificazione", "Classificazione")]
    EFFORT = [("", "Predefinito del modello"), ("low", "Basso"), ("medium", "Medio"), ("high", "Alto"),
              ("xhigh", "Molto alto"), ("max", "Massimo")]
    nome = models.CharField("nome", max_length=80)
    compito = models.CharField("compito", max_length=20, choices=COMPITI, default="chat")
    app = models.CharField("solo per l'app", max_length=31, blank=True, help_text="slug; vuoto = tutte")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, null=True, blank=True,
                                verbose_name="solo per l'azienda")
    effort = models.CharField("impegno di ragionamento", max_length=6, choices=EFFORT, blank=True)
    max_token = models.PositiveIntegerField("token massimi di risposta", default=16000)
    attivo = models.BooleanField("attivo", default=True)

    class Meta:
        verbose_name = "profilo"
        verbose_name_plural = "profili"
        ordering = ["compito", "app", "nome"]

    def __str__(self):
        return self.nome


class AnelloCatena(models.Model):
    """Un modello nella catena di un profilo: si prova in ordine, il successivo solo se il precedente fallisce
    prima di rispondere."""
    profilo = models.ForeignKey(Profilo, on_delete=models.CASCADE, related_name="catena", verbose_name="profilo")
    modello = models.ForeignKey(Modello, on_delete=models.PROTECT, verbose_name="modello")
    ordine = models.PositiveSmallIntegerField("ordine", default=1)

    class Meta:
        verbose_name = "modello della catena"
        verbose_name_plural = "catena dei modelli"
        ordering = ["ordine", "pk"]


class Turno(models.Model):
    """Un'esecuzione dell'assistente: dalla domanda alla risposta, con i passi, il costo e lo stato.
    `testo` cresce mentre il modello scrive (lo streaming lo segue); il resto è nel log degli eventi."""
    IN_CORSO, COMPLETATO, ERRORE, INTERROTTO, FERMATO = "in_corso", "completato", "errore", "interrotto", "fermato"
    STATI = [(IN_CORSO, "In corso"), (COMPLETATO, "Completato"), (ERRORE, "Errore"), (INTERROTTO, "Interrotto"),
             (FERMATO, "Fermato dall'utente")]
    conversazione = models.ForeignKey(Conversazione, on_delete=models.CASCADE, null=True, blank=True,
                                      related_name="turni", verbose_name="conversazione")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+",
                               verbose_name="utente")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="azienda")
    compito = models.CharField("compito", max_length=20, default="chat")
    stato = models.CharField("stato", max_length=10, choices=STATI, default=IN_CORSO)
    modello = models.ForeignKey(Modello, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="modello")
    testo = models.TextField("testo della risposta", blank=True)
    avanzamento = models.JSONField("avanzamento", default=list, blank=True)
    passi = models.PositiveSmallIntegerField("passi", default=0)
    uso = models.JSONField("token", default=dict, blank=True)
    costo = models.DecimalField("costo ($)", max_digits=12, decimal_places=6, default=0)
    errore = models.TextField("errore", blank=True)
    richiesta_stop = models.BooleanField("stop richiesto", default=False)
    iniziato = models.DateTimeField("iniziato il", auto_now_add=True)
    battito = models.DateTimeField("ultimo segno di vita", auto_now_add=True)
    finito = models.DateTimeField("finito il", null=True, blank=True)

    class Meta:
        verbose_name = "turno"
        verbose_name_plural = "turni"
        ordering = ["-pk"]
        indexes = [models.Index(fields=["azienda", "iniziato"])]

    def __str__(self):
        return f"Turno {self.pk} · {self.get_stato_display()}"

    @property
    def concluso(self):
        return self.stato != self.IN_CORSO


class Evento(models.Model):
    """Log in sola aggiunta della conversazione: ciò che il modello vede è ricostruito solo da qui."""
    UTENTE, ASSISTENTE, STRUMENTO = "utente", "assistente", "strumento"
    TIPI = [(UTENTE, "Utente"), (ASSISTENTE, "Assistente"), (STRUMENTO, "Risultati degli strumenti")]
    conversazione = models.ForeignKey(Conversazione, on_delete=models.CASCADE, related_name="eventi")
    turno = models.ForeignKey(Turno, on_delete=models.CASCADE, null=True, blank=True, related_name="eventi")
    tipo = models.CharField("tipo", max_length=10, choices=TIPI)
    dati = models.JSONField("dati", default=dict)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta:
        verbose_name = "evento"
        verbose_name_plural = "eventi"
        ordering = ["pk"]
        indexes = [models.Index(fields=["conversazione", "id"])]


class Proposta(models.Model):
    """Una modifica preparata dall'assistente che aspetta la conferma dell'utente. Alla conferma si esegue
    l'operazione salvata qui (strumento e argomenti), mai argomenti nuovi."""
    IN_ATTESA, ESEGUITA, ANNULLATA, FALLITA, SCADUTA = "in_attesa", "eseguita", "annullata", "fallita", "scaduta"
    STATI = [(IN_ATTESA, "In attesa di conferma"), (ESEGUITA, "Eseguita"), (ANNULLATA, "Annullata"),
             (FALLITA, "Non riuscita"), (SCADUTA, "Scaduta")]
    SCRITTURA, IRREVERSIBILE = "scrittura", "irreversibile"
    RISCHI = [(SCRITTURA, "Modifica"), (IRREVERSIBILE, "Irreversibile")]
    conversazione = models.ForeignKey(Conversazione, on_delete=models.CASCADE, related_name="proposte",
                                      verbose_name="conversazione")
    turno = models.ForeignKey(Turno, on_delete=models.SET_NULL, null=True, blank=True, related_name="proposte",
                              verbose_name="turno")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+",
                               verbose_name="utente")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, null=True, blank=True, verbose_name="azienda")
    strumento = models.CharField("strumento", max_length=80)
    argomenti = models.JSONField("argomenti", default=dict)
    titolo = models.CharField("titolo", max_length=250)
    dettagli = models.JSONField("dettagli", default=list, blank=True,
                                help_text='[{"campo", "prima", "dopo"}] mostrati nella scheda')
    riepilogo = models.TextField("riepilogo", blank=True)
    rischio = models.CharField("rischio", max_length=13, choices=RISCHI, default=SCRITTURA)
    impronta = models.JSONField("impronta del record", default=dict, blank=True)
    url = models.CharField("link", max_length=300, blank=True)
    stato = models.CharField("stato", max_length=10, choices=STATI, default=IN_ATTESA)
    esito = models.TextField("esito", blank=True)
    comunicata = models.BooleanField("esito comunicato all'assistente", default=False)
    creata = models.DateTimeField("creata il", auto_now_add=True)
    decisa = models.DateTimeField("decisa il", null=True, blank=True)

    class Meta:
        verbose_name = "proposta"
        verbose_name_plural = "proposte"
        ordering = ["pk"]

    def __str__(self):
        return self.titolo

    DURATA = timedelta(hours=24)                 # oltre, la proposta scade: i dati potrebbero essere cambiati

    @property
    def in_attesa(self):
        return self.stato == self.IN_ATTESA

    @property
    def scaduta(self):
        return self.in_attesa and timezone.now() - self.creata > self.DURATA

    @property
    def irreversibile(self):
        return self.rischio == self.IRREVERSIBILE


class Artifact(models.Model):
    """Grafico o tabella mostrato sotto una risposta: specifica scritta dal modello, dati calcolati dal codice
    (istantanea del momento). Salvato, resta nei pannelli della chat."""
    GRAFICO, TABELLA = "grafico", "tabella"
    TIPI = [(GRAFICO, "Grafico"), (TABELLA, "Tabella")]
    conversazione = models.ForeignKey(Conversazione, on_delete=models.CASCADE, null=True, blank=True,
                                      related_name="artifact", verbose_name="conversazione")
    turno = models.ForeignKey(Turno, on_delete=models.SET_NULL, null=True, blank=True, related_name="artifact",
                              verbose_name="turno")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+",
                               verbose_name="utente")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, null=True, blank=True, verbose_name="azienda")
    tipo = models.CharField("tipo", max_length=8, choices=TIPI)
    titolo = models.CharField("titolo", max_length=200)
    spec = models.JSONField("specifica", default=dict)
    dati = models.JSONField("dati (istantanea)", default=dict)
    salvato = models.BooleanField("salvato", default=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    aggiornato = models.DateTimeField("ricalcolato il", null=True, blank=True)

    class Meta:
        verbose_name = "artifact"
        verbose_name_plural = "artifact"
        ordering = ["pk"]

    def __str__(self):
        return self.titolo


class Pianificata(models.Model):
    """Un'istruzione che l'assistente esegue da solo a intervalli (o prima degli eventi del calendario), con i
    permessi del proprietario. Il risultato va nella sua conversazione e, se scelto, in Discuss o per email."""
    ORE, GIORNI, MESE, EVENTI = "ore", "giorni", "mese", "eventi"
    RICORRENZE = [(GIORNI, "Nei giorni della settimana scelti"), (MESE, "Ogni mese"), (ORE, "Ogni N ore"),
                  (EVENTI, "Prima degli eventi del calendario")]
    GIORNI_SETTIMANA = [(0, "lunedì"), (1, "martedì"), (2, "mercoledì"), (3, "giovedì"), (4, "venerdì"),
                        (5, "sabato"), (6, "domenica")]
    MAX_ERRORI = 3
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pianificate_ai",
                               verbose_name="proprietario")
    azienda = models.ForeignKey("core.Azienda", on_delete=models.CASCADE, null=True, blank=True, verbose_name="azienda")
    nome = models.CharField("nome", max_length=120)
    istruzioni = models.TextField("istruzioni", help_text="cosa deve fare l'assistente, come in chat")
    ambito = models.CharField("solo per l'app", max_length=31, blank=True, help_text="slug; vuoto = tutte")
    ricorrenza = models.CharField("quando", max_length=6, choices=RICORRENZE, default=GIORNI)
    alle = models.TimeField("alle ore", null=True, blank=True, help_text="per giorni della settimana e mese")
    giorni = models.CharField("giorni della settimana", max_length=20, blank=True, default="0,1,2,3,4",
                              help_text="0 = lunedì … 6 = domenica, separati da virgole")
    giorno_mese = models.PositiveSmallIntegerField("giorno del mese", null=True, blank=True,
                                                   help_text="1-28; per «ogni mese»")
    ogni_ore = models.PositiveSmallIntegerField("ogni quante ore", null=True, blank=True)
    minuti_prima = models.PositiveSmallIntegerField("minuti prima dell'evento", null=True, blank=True)
    in_discuss = models.BooleanField("invia anche in Discuss", default=True)
    per_email = models.BooleanField("invia anche per email", default=False)
    attiva = models.BooleanField("attiva", default=True)
    prossima = models.DateTimeField("prossima esecuzione", null=True, blank=True)
    ultima = models.DateTimeField("ultima esecuzione", null=True, blank=True)
    esito = models.CharField("ultimo esito", max_length=300, blank=True)
    errori = models.PositiveSmallIntegerField("errori di fila", default=0)
    eventi_fatti = models.JSONField("eventi già preparati", default=list, blank=True, editable=False)
    conversazione = models.ForeignKey(Conversazione, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+", verbose_name="conversazione")
    creata = models.DateTimeField("creata il", auto_now_add=True)

    class Meta:
        verbose_name = "attività pianificata"
        verbose_name_plural = "attività pianificate"
        ordering = ["nome", "pk"]
        indexes = [models.Index(fields=["attiva", "prossima"])]

    def __str__(self):
        return self.nome

    def elenco_giorni(self):
        return sorted({int(g) for g in self.giorni.split(",") if g.strip().isdigit() and 0 <= int(g) <= 6})

    def frequenza(self):
        """La ricorrenza in italiano: «lun-ven alle 08:00», «ogni 2 ore», «il 1 di ogni mese alle 09:00»."""
        ora = f" alle {self.alle:%H:%M}" if self.alle else ""
        if self.ricorrenza == self.ORE:
            return f"ogni {self.ogni_ore or 1} ore" if (self.ogni_ore or 1) > 1 else "ogni ora"
        if self.ricorrenza == self.MESE:
            return f"il {self.giorno_mese or 1} di ogni mese{ora}"
        if self.ricorrenza == self.EVENTI:
            return f"{self.minuti_prima or 30} minuti prima di ogni evento del calendario"
        giorni = self.elenco_giorni()
        nomi = dict(self.GIORNI_SETTIMANA)
        if giorni == list(range(7)):
            testo = "ogni giorno"
        elif giorni == list(range(5)):
            testo = "dal lunedì al venerdì"
        elif len(giorni) == 1:
            testo = f"ogni {nomi[giorni[0]]}"
        else:
            testo = "ogni " + ", ".join(nomi[g] for g in giorni[:-1]) + f" e {nomi[giorni[-1]]}"
        return testo + ora


class Licenza(models.Model):
    """File di licenza caricato (JSON firmato da ICHNOBYTE): vale l'ultimo caricato."""
    testo = models.TextField("licenza")
    caricata_il = models.DateTimeField("caricata il", auto_now_add=True)
    caricata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="caricata da")

    class Meta:
        verbose_name = "licenza"
        verbose_name_plural = "licenze"
        ordering = ["-pk"]
