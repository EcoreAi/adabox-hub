"""L'impostazione del servizio di previsione (dell'istanza) e le previsioni salvate di ogni azienda."""
from django.apps import apps
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


if apps.is_installed("magazzino"):
    # Chiavi esterne verso Magazzino e Prodotti in un modulo che non dipende da loro: il modello esiste solo con
    # Magazzino (che dipende da Prodotti) e la migrazione 0004 lo crea solo allora. Una migrazione futura che tocca
    # questo modello va scritta con la stessa condizione.
    class PrevisioneArticolo(AziendaMixin):
        """La previsione salvata di un articolo: per magazzino dove l'articolo ha una scorta di quel magazzino,
        altrimenti sul totale dell'azienda (magazzino vuoto). La ricalcolano il lavoro della notte e «Aggiorna»."""
        STATI = [("ok", "In ordine"), ("riordina_ora", "Riordina ora"), ("finito", "Finito"),
                 ("nessun_consumo", "Nessun consumo previsto"), ("oltre", "Oltre l'orizzonte")]
        PER = [("mese", "mese"), ("settimana", "settimana")]

        prodotto = models.ForeignKey("prodotti.Prodotto", on_delete=models.CASCADE, related_name="previsioni_articolo",
                                     verbose_name="prodotto")
        magazzino = models.ForeignKey("magazzino.Magazzino", on_delete=models.CASCADE, null=True, blank=True,
                                      related_name="previsioni_articolo", verbose_name="magazzino",
                                      help_text="vuoto: sul totale dei magazzini dell'azienda")
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
        quantita_suggerita = models.DecimalField("quantità suggerita", max_digits=14, decimal_places=3, null=True,
                                                 blank=True)
        stato = models.CharField("stato", max_length=20, choices=STATI)
        affidabilita = models.JSONField("affidabilità", default=dict)
        modello = models.CharField("modello", max_length=120, blank=True)
        calcolata_il = models.DateTimeField("calcolata il")

        class Meta(AziendaMixin.Meta):
            verbose_name = "previsione di un articolo"
            verbose_name_plural = "previsioni degli articoli"
            constraints = [
                models.UniqueConstraint(fields=["azienda", "prodotto", "magazzino"],
                                        condition=models.Q(magazzino__isnull=False), name="previsioni_articolo_magazzino"),
                models.UniqueConstraint(fields=["azienda", "prodotto"], condition=models.Q(magazzino__isnull=True),
                                        name="previsioni_articolo_totale"),
            ]

        def __str__(self):
            return f"Previsione di {self.prodotto} ({self.magazzino or 'tutti i magazzini'})"
