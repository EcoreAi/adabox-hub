"""L'impostazione del servizio di previsione (dell'istanza) e le previsioni salvate di ogni azienda."""
from django.conf import settings
from django.db import models

from core import cifratura
from core.mixins import AziendaMixin


class ServizioPrevisioni(models.Model):
    """Una sola riga: la chiave d'accesso al servizio, cifrata e mai mostrata. L'URL sta nelle impostazioni del modulo."""
    chiave_cifrata = models.TextField(blank=True, editable=False)

    class Meta:
        verbose_name = "servizio di previsione"
        verbose_name_plural = "servizio di previsione"

    @classmethod
    def corrente(cls):
        return cls.objects.order_by("pk").first() or cls.objects.create()

    @property
    def chiave(self):
        return cifratura.decifra(self.chiave_cifrata)

    def __str__(self):
        return "Servizio di previsione"


class StatoCalcolo(AziendaMixin):
    """L'ultimo calcolo delle previsioni salvate di un'azienda, per tipo: quando si è provato, quando è riuscito e, se
    l'ultimo tentativo è fallito, perché. Le previsioni salvate restano quelle dell'ultimo calcolo riuscito."""
    MAGAZZINO, VENDITE = "magazzino", "vendite"
    COSE = [(MAGAZZINO, "Magazzino"), (VENDITE, "Vendite")]

    cosa = models.CharField("previsioni di", max_length=20, choices=COSE)
    ultimo_tentativo = models.DateTimeField("ultimo tentativo", null=True, blank=True)
    ultimo_ok = models.DateTimeField("ultimo calcolo riuscito", null=True, blank=True)
    errore = models.TextField("errore dell'ultimo tentativo", blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "stato del calcolo"
        verbose_name_plural = "stati del calcolo"
        constraints = [models.UniqueConstraint(fields=["azienda", "cosa"], name="previsioni_stato_unico")]

    def __str__(self):
        return f"Previsioni di {self.get_cosa_display().lower()}"


class PrevisioneArticolo(AziendaMixin):
    """La previsione salvata di un articolo: per magazzino dove l'articolo ha una scorta di quel magazzino, altrimenti
    sul totale dell'azienda (magazzino vuoto). La ricalcolano il lavoro della notte e «Aggiorna».

    Il modulo non dipende da Magazzino né da Prodotti, che possono arrivare dopo: niente chiavi esterne verso di loro,
    ma i loro id e i nomi copiati al momento del calcolo. Le righe si creano solo con Magazzino installato."""
    STATI = [("ok", "In ordine"), ("riordina_ora", "Riordina ora"), ("finito", "Finito"),
             ("nessun_consumo", "Nessun consumo previsto"), ("oltre", "Oltre l'orizzonte")]
    PER = [("mese", "mese"), ("settimana", "settimana")]

    prodotto_pk = models.PositiveBigIntegerField("id del prodotto", db_index=True)
    prodotto = models.CharField("prodotto", max_length=200)
    codice = models.CharField("codice", max_length=40, blank=True)
    magazzino_pk = models.PositiveBigIntegerField("id del magazzino", null=True, blank=True,
                                                  help_text="vuoto: sul totale dei magazzini dell'azienda")
    magazzino = models.CharField("magazzino", max_length=80, blank=True)
    per = models.CharField("periodo", max_length=10, choices=PER)
    partenza = models.DecimalField("giacenza prevista", max_digits=14, decimal_places=3,
                                   help_text="giacenza + in arrivo − impegnato al momento del calcolo")
    futuro = models.JSONField("consumo previsto", default=list,
                              help_text="[[periodo, 10 %, mediana, 90 %]] dal periodo in corso")
    consumo_mensile = models.DecimalField("consumo previsto al mese", max_digits=14, decimal_places=3,
                                          help_text="media delle mediane, riportata al mese")
    esaurimento = models.DateField("esaurimento", null=True, blank=True)
    esaurimento_da = models.DateField("esaurimento dal", null=True, blank=True, help_text="con il consumo alto (90 %)")
    esaurimento_a = models.DateField("esaurimento entro", null=True, blank=True, help_text="con il consumo basso (10 %)")
    riordino = models.DateField("riordino", null=True, blank=True)
    quantita_suggerita = models.DecimalField("quantità suggerita", max_digits=14, decimal_places=3, null=True, blank=True)
    stato = models.CharField("stato", max_length=20, choices=STATI)
    affidabilita = models.JSONField("affidabilità", default=dict)
    modello = models.CharField("modello", max_length=120, blank=True)
    calcolata_il = models.DateTimeField("calcolata il")

    class Meta(AziendaMixin.Meta):
        verbose_name = "previsione di un articolo"
        verbose_name_plural = "previsioni degli articoli"
        # con magazzino_pk vuoto il vincolo non impedirebbe due righe uguali (NULL è sempre diverso da NULL), ma le
        # righe di un'azienda si sostituiscono sempre tutte insieme (calcolo.py), una per chiave
        constraints = [models.UniqueConstraint(fields=["azienda", "prodotto_pk", "magazzino_pk"],
                                               name="previsioni_articolo_unico")]

    def __str__(self):
        return f"Previsione di {self.prodotto} ({self.magazzino or 'tutti i magazzini'})"


class PrevisionePronta(AziendaMixin):
    """Una previsione pronta (pronte.py) salvata per l'azienda: calcolata con l'accesso all'intera azienda, la vede
    solo chi vede tutta la vista di origine. La ricalcolano il lavoro della notte e «Aggiorna».

    `dati` = {"spec": la specifica calcolata, "risultato": quello del motore} oppure, se la storia non bastava,
    {"spec", "errore"}. Niente chiavi esterne verso altri moduli, come PrevisioneArticolo."""
    chiave = models.CharField("previsione", max_length=80, help_text="la chiave del registro, es. vendite.prodotti")
    dati = models.JSONField("dati", default=dict)
    modello = models.CharField("modello", max_length=120, blank=True)
    calcolata_il = models.DateTimeField("calcolata il")

    class Meta(AziendaMixin.Meta):
        verbose_name = "previsione pronta"
        verbose_name_plural = "previsioni pronte"
        constraints = [models.UniqueConstraint(fields=["azienda", "chiave"], name="previsioni_pronta_unica")]

    def __str__(self):
        return f"Previsione pronta {self.chiave}"


class EtichettaPrevisione(AziendaMixin):
    """L'etichetta che l'utente dà a una sua previsione (di una chat o di Analisi) per ritrovarla in «Le mie previsioni».

    Niente chiavi esterne verso Assistente AI e Analisi, che possono arrivare dopo (come PrevisioneArticolo): l'origine e
    l'id dell'oggetto. L'etichetta è dell'utente, non dell'azienda: l'azienda è quella in cui l'ha scritta."""
    CHAT, ANALISI = "chat", "analisi"
    ORIGINI = [(CHAT, "Chat"), (ANALISI, "Analisi")]

    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+", verbose_name="utente")
    origine = models.CharField("origine", max_length=10, choices=ORIGINI)
    oggetto_pk = models.PositiveBigIntegerField("id della previsione")
    etichetta = models.CharField("etichetta", max_length=60)

    class Meta(AziendaMixin.Meta):
        verbose_name = "etichetta di una previsione"
        verbose_name_plural = "etichette delle previsioni"
        constraints = [models.UniqueConstraint(fields=["utente", "origine", "oggetto_pk"], name="previsioni_etichetta_unica")]

    def __str__(self):
        return f"{self.etichetta} ({self.origine} {self.oggetto_pk})"
