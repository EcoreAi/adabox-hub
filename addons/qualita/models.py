from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count

from core.mixins import AziendaMixin


class Ambiente(AziendaMixin):
    SVILUPPO, COLLAUDO, PRODUZIONE = "sviluppo", "collaudo", "produzione"
    progetto = models.ForeignKey("progetti.Progetto", on_delete=models.CASCADE, related_name="ambienti",
                                 verbose_name="progetto")
    nome = models.CharField("nome", max_length=100)
    tipo = models.CharField("tipo", max_length=12, default=COLLAUDO,
                            choices=[(SVILUPPO, "Sviluppo"), (COLLAUDO, "Collaudo"), (PRODUZIONE, "Produzione")])
    url = models.URLField("indirizzo", blank=True)
    rilascio = models.ForeignKey("progetti.Rilascio", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="ambienti", verbose_name="versione installata")
    note = models.TextField("note", blank=True, help_text="accessi di prova, dati di test (niente password vere)")

    class Meta(AziendaMixin.Meta):
        verbose_name = "ambiente"
        verbose_name_plural = "ambienti"
        ordering = ["progetto", "tipo", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.progetto})"

    def clean(self):
        if self.rilascio_id and self.progetto_id and self.rilascio.progetto_id != self.progetto_id:
            raise ValidationError({"rilascio": "Scegli un rilascio dello stesso progetto."})


class CasoTest(AziendaMixin):
    ALTA, MEDIA, BASSA = "alta", "media", "bassa"
    progetto = models.ForeignKey("progetti.Progetto", on_delete=models.CASCADE, related_name="casi_test",
                                 verbose_name="progetto")
    titolo = models.CharField("titolo", max_length=200)
    area = models.CharField("area", max_length=100, blank=True, help_text="es. Ordini, Login, Stampe")
    precondizioni = models.TextField("precondizioni", blank=True)
    passi = models.TextField("passi", help_text="uno per riga")
    atteso = models.TextField("risultato atteso")
    priorita = models.CharField("priorità", max_length=5, default=MEDIA,
                                choices=[(ALTA, "Alta"), (MEDIA, "Media"), (BASSA, "Bassa")])
    attivo = models.BooleanField("attivo", default=True, help_text="i casi non attivi non entrano nei collaudi nuovi")

    class Meta(AziendaMixin.Meta):
        verbose_name = "caso di test"
        verbose_name_plural = "casi di test"
        ordering = ["progetto", "area", "pk"]

    def __str__(self):
        return f"{self.area} · {self.titolo}" if self.area else self.titolo

    def elenco_passi(self):
        return [p.strip() for p in self.passi.splitlines() if p.strip()]


class Collaudo(AziendaMixin):
    APERTO, CONCLUSO = "aperto", "concluso"
    progetto = models.ForeignKey("progetti.Progetto", on_delete=models.CASCADE, related_name="collaudi",
                                 verbose_name="progetto")
    nome = models.CharField("nome", max_length=200)
    rilascio = models.ForeignKey("progetti.Rilascio", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="collaudi", verbose_name="rilascio")
    ambiente = models.ForeignKey(Ambiente, on_delete=models.SET_NULL, null=True, blank=True, related_name="collaudi",
                                 verbose_name="ambiente")
    responsabile = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="collaudi", verbose_name="responsabile")
    stato = models.CharField("stato", max_length=8, default=APERTO,
                             choices=[(APERTO, "Aperto"), (CONCLUSO, "Concluso")])
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "collaudo"
        verbose_name_plural = "collaudi"
        ordering = ["-creato", "-pk"]

    def __str__(self):
        return self.nome

    def clean(self):
        errori = {}
        if self.rilascio_id and self.progetto_id and self.rilascio.progetto_id != self.progetto_id:
            errori["rilascio"] = "Scegli un rilascio dello stesso progetto."
        if self.ambiente_id and self.progetto_id and self.ambiente.progetto_id != self.progetto_id:
            errori["ambiente"] = "Scegli un ambiente dello stesso progetto."
        if errori:
            raise ValidationError(errori)

    def aggiungi_casi(self):
        """Aggiunge i casi attivi del progetto non ancora presenti; restituisce quanti."""
        presenti = self.esecuzioni.values("caso")
        nuovi = [Esecuzione(collaudo=self, caso=c) for c in
                 CasoTest.objects.filter(progetto_id=self.progetto_id, attivo=True).exclude(pk__in=presenti)]
        Esecuzione.objects.bulk_create(nuovi)
        return len(nuovi)

    def riepilogo(self):
        """{esito: numero} per tutti gli esiti, più totale e percentuale eseguita."""
        conteggi = dict(self.esecuzioni.values_list("esito").annotate(n=Count("pk")))
        r = {e: conteggi.get(e, 0) for e, _ in Esecuzione.ESITI}
        r["totale"] = sum(conteggi.values())
        eseguiti = r["totale"] - r[Esecuzione.DA_FARE]
        r["percentuale"] = round(100 * eseguiti / r["totale"]) if r["totale"] else 0
        return r

    def esito(self):
        """«superato», «fallito», «in corso» o «vuoto»."""
        r = self.riepilogo()
        if not r["totale"]:
            return "vuoto"
        if r[Esecuzione.FALLITO] or r[Esecuzione.BLOCCATO]:
            return "fallito"
        return "in corso" if r[Esecuzione.DA_FARE] else "superato"


class Esecuzione(models.Model):
    DA_FARE, SUPERATO, FALLITO, BLOCCATO, SALTATO = "da_fare", "superato", "fallito", "bloccato", "saltato"
    ESITI = [(DA_FARE, "Da fare"), (SUPERATO, "Superato"), (FALLITO, "Fallito"), (BLOCCATO, "Bloccato"),
             (SALTATO, "Saltato")]
    collaudo = models.ForeignKey(Collaudo, on_delete=models.CASCADE, related_name="esecuzioni",
                                 verbose_name="collaudo")
    caso = models.ForeignKey(CasoTest, on_delete=models.CASCADE, related_name="esecuzioni", verbose_name="caso")
    esito = models.CharField("esito", max_length=8, choices=ESITI, default=DA_FARE)
    note = models.TextField("note", blank=True)
    eseguito_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="eseguito da")
    eseguito_il = models.DateTimeField("eseguito il", null=True, blank=True)
    difetto = models.ForeignKey("progetti.Compito", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="esecuzioni_fallite", verbose_name="difetto")

    class Meta:
        verbose_name = "esecuzione"
        verbose_name_plural = "esecuzioni"
        ordering = ["caso__area", "caso__pk"]
        constraints = [models.UniqueConstraint(fields=["collaudo", "caso"], name="esecuzione_unica")]

    def __str__(self):
        return f"{self.caso} · {self.get_esito_display()}"
