"""Wiki interna: spazi (aperti a tutta l'azienda o ai soli membri, che leggono o scrivono), pagine ad albero in
markdown con le loro versioni."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.mixins import AziendaMixin


class SpazioWiki(AziendaMixin):
    nome = models.CharField("nome", max_length=100, help_text="es. Procedure, Commerciale, Tecnico")
    descrizione = models.TextField("descrizione", blank=True)
    aperto = models.BooleanField("tutta l'azienda legge", default=True,
                                 help_text="se no, solo i membri; scrivono sempre e solo i membri con «scrive» (e i responsabili della wiki)")
    membri = models.ManyToManyField(settings.AUTH_USER_MODEL, through="MembroWiki", blank=True, related_name="+", verbose_name="membri")

    class Meta(AziendaMixin.Meta):
        verbose_name = "spazio della wiki"
        verbose_name_plural = "spazi della wiki"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class MembroWiki(models.Model):
    LEGGE, SCRIVE = "legge", "scrive"
    spazio = models.ForeignKey(SpazioWiki, on_delete=models.CASCADE, related_name="iscritti", verbose_name="spazio")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+", verbose_name="persona")
    ruolo = models.CharField("ruolo", max_length=6, choices=[(LEGGE, "Legge"), (SCRIVE, "Legge e scrive")], default=SCRIVE)

    class Meta:
        verbose_name = "membro"
        verbose_name_plural = "membri"
        constraints = [models.UniqueConstraint(fields=["spazio", "utente"], name="wiki_membro_unico")]


class PaginaWiki(AziendaMixin):
    spazio = models.ForeignKey(SpazioWiki, on_delete=models.CASCADE, related_name="pagine", verbose_name="spazio")
    padre = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="figlie", verbose_name="sotto la pagina")
    titolo = models.CharField("titolo", max_length=200)
    testo = models.TextField("testo", blank=True,
                             help_text="markdown: # titoli, **grassetto**, - elenchi, [testo](/indirizzo/) per i record, [[Titolo]] per un'altra pagina")
    ordine = models.PositiveIntegerField("ordine", default=10)
    aggiornata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                      verbose_name="aggiornata da", editable=False)
    aggiornata_il = models.DateTimeField("aggiornata il", auto_now=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "pagina della wiki"
        verbose_name_plural = "pagine della wiki"
        ordering = ["spazio__nome", "ordine", "titolo"]

    def __str__(self):
        return self.titolo

    def clean(self):
        if self.padre_id:
            if self.padre.spazio_id != self.spazio_id:
                raise ValidationError({"padre": "La pagina sopra è di un altro spazio."})
            nodo, visti = self.padre, set()
            while nodo is not None and nodo.pk not in visti:
                if nodo.pk == self.pk:
                    raise ValidationError({"padre": "Una pagina non può stare sotto sé stessa."})
                visti.add(nodo.pk)
                nodo = nodo.padre

    def percorso(self):
        nodi, nodo, visti = [], self.padre, set()
        while nodo is not None and nodo.pk not in visti:
            visti.add(nodo.pk)
            nodi.append(nodo)
            nodo = nodo.padre
        return list(reversed(nodi))


class VersionePagina(models.Model):
    pagina = models.ForeignKey(PaginaWiki, on_delete=models.CASCADE, related_name="versioni", verbose_name="pagina")
    numero = models.PositiveIntegerField("versione")
    titolo = models.CharField("titolo", max_length=200)
    testo = models.TextField("testo", blank=True)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="autore")
    creata = models.DateTimeField("salvata il", auto_now_add=True)

    class Meta:
        verbose_name = "versione"
        verbose_name_plural = "versioni"
        ordering = ["-numero"]
        constraints = [models.UniqueConstraint(fields=["pagina", "numero"], name="wiki_versione_unica")]

    def __str__(self):
        return f"{self.pagina} v{self.numero}"
