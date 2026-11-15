"""Il legame tra una cartella dei Documenti e una cartella di una raccolta documenti di SharePoint."""
from django.db import models

from core import cifratura
from core.mixins import AziendaMixin


class CollegamentoSharePoint(AziendaMixin):
    """Una cartella dei Documenti tenuta allineata con una cartella di SharePoint, nel verso scelto. Le sottocartelle
    seguono: quelle di SharePoint diventano cartelle dei Documenti con lo stesso nome, e viceversa."""
    DA_SHAREPOINT, VERSO_SHAREPOINT, ENTRAMBI = "da_sharepoint", "verso_sharepoint", "entrambi"
    VERSI = [(DA_SHAREPOINT, "Da SharePoint ad adabox"), (VERSO_SHAREPOINT, "Da adabox a SharePoint"),
             (ENTRAMBI, "Nei due versi")]
    PROVA, VERA = "prova", "vera"
    MODALITA = [(PROVA, "Prova, senza uscire in rete"), (VERA, "Vera")]
    nome = models.CharField("nome", max_length=120, help_text="per riconoscerlo, es. «Contratti su SharePoint»")
    cartella = models.OneToOneField("documenti.Cartella", on_delete=models.PROTECT, related_name="sharepoint",
                                    verbose_name="cartella dei Documenti",
                                    help_text="i file arrivano qui e da qui partono, con le sottocartelle")
    verso = models.CharField("verso", max_length=20, choices=VERSI, default=DA_SHAREPOINT)
    modalita = models.CharField("modalità", max_length=8, choices=MODALITA, default=PROVA)
    attivo = models.BooleanField("attivo", default=True)
    sito = models.CharField("sito SharePoint", max_length=300, blank=True,
                            help_text="l'indirizzo del sito, es. https://azienda.sharepoint.com/sites/Ufficio")
    libreria = models.CharField("raccolta documenti", max_length=200, blank=True,
                                help_text="il nome della raccolta, es. «Documenti condivisi»; vuoto = quella predefinita del sito")
    percorso = models.CharField("cartella su SharePoint", max_length=400, blank=True,
                                help_text="dentro la raccolta, es. «Commerciale/Contratti»; vuoto = tutta la raccolta")
    tenant = models.CharField("tenant (ID della directory)", max_length=200, blank=True,
                              help_text="in Microsoft Entra ID → Panoramica; va bene anche il dominio azienda.onmicrosoft.com")
    client_id = models.CharField("client id (ID dell'applicazione)", max_length=200, blank=True)
    segreto_cifrato = models.TextField(blank=True, editable=False)
    accesso_cifrato = models.TextField(blank=True, editable=False)     # il token di accesso del momento
    accesso_scade = models.DateTimeField(null=True, blank=True, editable=False)
    drive_id = models.CharField(max_length=200, blank=True, editable=False)
    cartella_id_esterna = models.CharField(max_length=200, blank=True, editable=False)
    in_corso_dal = models.DateTimeField(null=True, blank=True, editable=False)
    ultimo_giro = models.DateTimeField("ultimo giro", null=True, blank=True, editable=False)
    ultimo_esito = models.CharField("ultimo esito", max_length=1000, blank=True, editable=False)
    in_errore = models.BooleanField("in errore", default=False, editable=False)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "collegamento SharePoint"
        verbose_name_plural = "collegamenti SharePoint"
        ordering = ["nome", "pk"]

    def __str__(self):
        return self.nome

    def segreto(self):
        return cifratura.decifra(self.segreto_cifrato)

    @property
    def legge(self):
        return self.verso in (self.DA_SHAREPOINT, self.ENTRAMBI)

    @property
    def scrive(self):
        return self.verso in (self.VERSO_SHAREPOINT, self.ENTRAMBI)


class FileSharePoint(AziendaMixin):
    """Questo documento corrisponde a quel file di SharePoint, com'erano entrambi all'ultimo allineamento: se ne
    cambia uno dei due, al giro dopo si copia nell'altro verso."""
    collegamento = models.ForeignKey(CollegamentoSharePoint, on_delete=models.CASCADE, related_name="file",
                                     verbose_name="collegamento")
    documento = models.ForeignKey("documenti.Documento", on_delete=models.CASCADE, related_name="file_sharepoint",
                                  verbose_name="documento")
    id_esterno = models.CharField("id su SharePoint", max_length=200)
    percorso = models.CharField("percorso su SharePoint", max_length=1000, help_text="dentro la cartella collegata")
    ctag = models.CharField("versione su SharePoint", max_length=300, blank=True)
    versione = models.PositiveIntegerField("versione in adabox", default=0)
    sincronizzato = models.DateTimeField("allineato il", auto_now=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "file su SharePoint"
        verbose_name_plural = "file su SharePoint"
        ordering = ["collegamento", "percorso"]
        constraints = [
            models.UniqueConstraint(fields=["collegamento", "id_esterno"], name="sharepoint_file_esterno_unico"),
            models.UniqueConstraint(fields=["collegamento", "documento"], name="sharepoint_file_documento_unico"),
        ]

    def __str__(self):
        return self.percorso


class FileProva(models.Model):
    """Un file (o una cartella) della SharePoint finta che risponde quando il collegamento è in prova."""
    collegamento = models.ForeignKey(CollegamentoSharePoint, on_delete=models.CASCADE, related_name="file_prova")
    id_esterno = models.CharField(max_length=40)
    percorso = models.CharField(max_length=1000, help_text="dalla radice della raccolta, es. «Adabox/Offerte/a.pdf»")
    cartella = models.BooleanField(default=False)
    contenuto = models.BinaryField(default=b"")
    ctag = models.CharField(max_length=80, blank=True)
    modificato = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "file di prova"
        verbose_name_plural = "file di prova"
        ordering = ["percorso"]
        constraints = [models.UniqueConstraint(fields=["collegamento", "percorso"], name="sharepoint_prova_percorso_unico")]

    def __str__(self):
        return self.percorso
