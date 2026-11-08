from django.conf import settings
from django.db import models


class Pagina(models.Model):
    """Una scheda della dashboard: la griglia di widget di un utente, libera o legata a un'app (il tab del CRM, della
    Fatturazione…). Non possiede i widget, li dispone: lo stesso widget può stare in tutte le pagine che si vuole.
    Il proprietario la dispone; condivisa, la vede tutta l'azienda ma ognuno con i propri dati."""
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pagine_analisi",
                               verbose_name="proprietario")
    titolo = models.CharField("titolo", max_length=100)
    icona = models.CharField("icona", max_length=30, default="bar-chart")
    app = models.CharField("app", max_length=30, blank=True, db_index=True, help_text="vuoto = pagina libera")
    ordine = models.PositiveSmallIntegerField("ordine", default=0)
    condivisa = models.BooleanField("condivisa con l'azienda", default=False)
    ruoli = models.ManyToManyField("core.Ruolo", blank=True, related_name="pagine_analisi", verbose_name="condivisa con i ruoli",
                                   help_text="la vedono le persone dell'azienda con uno di questi ruoli")
    gruppi = models.ManyToManyField("auth.Group", blank=True, related_name="pagine_analisi", verbose_name="condivisa con i gruppi")
    nascosta = models.BooleanField("nascosta", default=False, help_text="la scheda dell'app non compare tra le schede")
    # l'area di lavoro dell'assistente di cui è la dashboard: numero e non chiave esterna, Analisi non dipende da ai
    area = models.PositiveIntegerField("area di lavoro", null=True, blank=True, unique=True,
                                       help_text="la dashboard dell'area: la vedono e la dispongono i suoi membri")
    layout = models.JSONField("disposizione", default=dict, blank=True,
                              help_text='{"widget": [{"id": "g:12", "w": 2}, …], "nascosti": ["crm:g0", …]}')
    creata = models.DateTimeField("creata il", auto_now_add=True)
    aggiornata = models.DateTimeField("aggiornata il", auto_now=True)

    class Meta:
        verbose_name = "pagina"
        verbose_name_plural = "pagine"
        ordering = ["ordine", "pk"]
        permissions = [("condividi_pagina", "Può condividere una pagina con tutta l'azienda")]

    def __str__(self):
        return self.titolo

    @property
    def chiave(self):
        return f"app:{self.app}" if self.app else f"pagina:{self.pk}"

    @property
    def id_widget(self):
        """Gli id dei widget che la pagina mostra: la pagina è una disposizione, i widget stanno nella libreria."""
        return [v["id"] for v in (self.layout or {}).get("widget", []) if isinstance(v, dict) and v.get("id")]

    @property
    def n_widget(self):
        return len(self.id_widget)


class Grafico(models.Model):
    """Un grafico salvato: la specifica della query (vista, raggruppamento, misura, filtri), il tipo con cui si disegna
    e l'ultima istantanea dei dati. Si ricalcola quando serve, sempre con i permessi di chi guarda."""
    BARRE, BARRE_ORIZZONTALI, LINEE, AREA, TORTA, KPI, PREVISIONE, TABELLA = (
        "barre", "barre_orizzontali", "linee", "area", "torta", "kpi", "previsione", "tabella")
    TIPI = [(BARRE, "Barre"), (BARRE_ORIZZONTALI, "Barre orizzontali"), (LINEE, "Linee"), (AREA, "Area"),
            (TORTA, "Torta"), (KPI, "KPI"), (PREVISIONE, "Previsione"), (TABELLA, "Tabella")]
    INTERCAMBIABILI = (BARRE, BARRE_ORIZZONTALI, LINEE, AREA, TORTA)       # stessa serie, disegno diverso
    CHAT, VISTA, COSTRUTTORE = "chat", "vista", "costruttore"
    ORIGINI = [(CHAT, "Chiesto ad Ada"), (VISTA, "Dalla vista Grafico"), (COSTRUTTORE, "Costruttore")]
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="grafici_analisi",
                               verbose_name="proprietario")
    condiviso_con = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="grafici_condivisi", verbose_name="condiviso con",
                                           help_text="lo vedono nella loro libreria, con i dati che i loro permessi consentono")
    titolo = models.CharField("titolo", max_length=200)
    tipo = models.CharField("tipo", max_length=20, choices=TIPI, default=BARRE)
    spec = models.JSONField("specifica", default=dict,
                            help_text='{"vista": "vendite.ordini", "per": "data:mese", "misura": "sum:totale", "filtri": {…}}')
    opzioni = models.JSONField("opzioni", default=dict, blank=True)
    dati = models.JSONField("dati (ultima istantanea)", default=dict, blank=True)
    aggiornato = models.DateTimeField("dati aggiornati il", null=True, blank=True)
    aggiorna_ogni = models.PositiveIntegerField("aggiorna ogni (ore)", default=0, help_text="0 = solo a mano")
    origine = models.CharField("origine", max_length=12, choices=ORIGINI, default=COSTRUTTORE)
    origine_url = models.CharField("indirizzo d'origine", max_length=300, blank=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)
    modificato = models.DateTimeField("modificato il", auto_now=True)

    class Meta:
        verbose_name = "grafico"
        verbose_name_plural = "grafici"
        ordering = ["pk"]

    def __str__(self):
        return self.titolo

    @property
    def id_widget(self):
        return f"g:{self.pk}"

    @property
    def vista(self):
        return (self.spec or {}).get("vista", "")
