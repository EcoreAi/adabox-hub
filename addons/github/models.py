import re
import secrets

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from core import cifratura
from core.mixins import AziendaMixin

NOME_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def nuovo_segreto():
    return secrets.token_urlsafe(32)


def prefisso():
    from core import parametri
    try:
        return (parametri.leggi("github.prefisso") or "ADA").strip().upper()
    except KeyError:
        return "ADA"


def riferimento(compito):
    return f"{prefisso()}-{compito.pk}"


def ramo_suggerito(compito):
    return f"{prefisso().lower()}-{compito.pk}-{slugify(compito.titolo)[:40].strip('-')}"


def riferimenti(*testi):
    """Gli id dei compiti citati («ADA-123», anche nei nomi dei rami «ada-123-...»), senza doppioni."""
    schema = re.compile(rf"(?<![A-Za-z0-9]){re.escape(prefisso())}-(\d+)(?![A-Za-z0-9])", re.IGNORECASE)
    trovati = []
    for testo in testi:
        for n in schema.findall(testo or ""):
            if int(n) not in trovati:
                trovati.append(int(n))
    return trovati


class Repository(AziendaMixin):
    progetto = models.ForeignKey("progetti.Progetto", on_delete=models.CASCADE, related_name="repository",
                                 verbose_name="progetto")
    nome = models.CharField("repository", max_length=200, unique=True, help_text="proprietario/nome, es. ichnobyte/gestionale")
    segreto = models.CharField("segreto del webhook", max_length=64, default=nuovo_segreto, editable=False)
    token_cifrato = models.TextField("token", blank=True, editable=False)
    chiudi_al_merge = models.BooleanField("chiudi il compito al merge", default=True,
                                          help_text="una pull request unita completa i compiti che cita")
    attivo = models.BooleanField("attivo", default=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "repository"
        verbose_name_plural = "repository"
        ordering = ["nome"]

    def __str__(self):
        return self.nome

    def clean(self):
        if self.nome and not NOME_REPO.match(self.nome):
            raise ValidationError({"nome": "Scrivi proprietario/nome, es. ichnobyte/gestionale."})

    @property
    def token(self):
        return cifratura.decifra(self.token_cifrato)

    @token.setter
    def token(self, valore):
        self.token_cifrato = cifratura.cifra(valore.strip()) if valore else ""

    @property
    def url(self):
        return f"https://github.com/{self.nome}"


class Collegamento(models.Model):
    COMMIT, PULL_REQUEST, ISSUE = "commit", "pr", "issue"
    APERTA, UNITA, CHIUSA = "aperta", "unita", "chiusa"
    compito = models.ForeignKey("progetti.Compito", on_delete=models.CASCADE, related_name="collegamenti_github",
                                verbose_name="compito")
    repository = models.ForeignKey(Repository, on_delete=models.CASCADE, related_name="collegamenti",
                                   verbose_name="repository")
    tipo = models.CharField("tipo", max_length=6,
                            choices=[(COMMIT, "Commit"), (PULL_REQUEST, "Pull request"), (ISSUE, "Issue")])
    chiave = models.CharField("sha o numero", max_length=64)
    titolo = models.CharField("titolo", max_length=300, blank=True)
    url = models.URLField("indirizzo", max_length=500)
    stato = models.CharField("stato", max_length=6, blank=True,
                             choices=[(APERTA, "Aperta"), (UNITA, "Unita"), (CHIUSA, "Chiusa")])
    autore = models.CharField("autore", max_length=100, blank=True)
    data = models.DateTimeField("data", auto_now_add=True)

    class Meta:
        verbose_name = "collegamento GitHub"
        verbose_name_plural = "collegamenti GitHub"
        ordering = ["-data", "-pk"]
        constraints = [models.UniqueConstraint(fields=["compito", "repository", "tipo", "chiave"],
                                               name="collegamento_github_unico")]

    def __str__(self):
        return f"{self.get_tipo_display()} {self.etichetta}"

    @property
    def etichetta(self):
        return self.chiave[:7] if self.tipo == self.COMMIT else f"#{self.chiave}"
