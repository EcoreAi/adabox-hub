from django.db import models

from core.mixins import AziendaMixin


class FornitorePagamento(AziendaMixin):
    """Il conto con cui l'azienda incassa online. Le chiavi si scrivono e si salvano cifrate, non si rileggono."""
    STRIPE, PAYPAL, FINTO = "stripe", "paypal", "finto"
    TIPI = [(STRIPE, "Stripe"), (PAYPAL, "PayPal"), (FINTO, "Simulato (prove e demo)")]
    nome = models.CharField("nome", max_length=80, default="Stripe")
    tipo = models.CharField("fornitore", max_length=10, choices=TIPI, default=STRIPE)
    client_id = models.CharField("Client ID", max_length=200, blank=True, help_text="Solo PayPal: dall'app creata nel portale sviluppatori")
    sandbox = models.BooleanField("ambiente di prova", default=False, help_text="Solo PayPal: usa la sandbox (nessun incasso vero)")
    chiave_cifrata = models.TextField(blank=True, editable=False)
    segreto_webhook_cifrato = models.TextField(blank=True, editable=False)
    attivo = models.BooleanField("attivo", default=True)
    creato = models.DateTimeField("creato il", auto_now_add=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "fornitore di pagamento"
        verbose_name_plural = "fornitori di pagamento"
        ordering = ["pk"]

    def __str__(self):
        return self.nome

    def chiave(self):
        from core import cifratura
        return cifratura.decifra(self.chiave_cifrata) if self.chiave_cifrata else ""

    def segreto_webhook(self):
        from core import cifratura
        return cifratura.decifra(self.segreto_webhook_cifrato) if self.segreto_webhook_cifrato else ""

    @property
    def di_prova(self):
        if self.tipo == self.PAYPAL:
            return self.sandbox
        return self.tipo == self.FINTO or self.chiave().startswith("sk_test_")


class Pagamento(AziendaMixin):
    """Un tentativo di pagamento online di una fattura. Diventa un incasso solo quando il fornitore lo conferma."""
    AVVIATO, PAGATO, FALLITO = "avviato", "pagato", "fallito"
    STATI = [(AVVIATO, "In corso"), (PAGATO, "Pagato"), (FALLITO, "Non riuscito")]
    fattura = models.ForeignKey("fatturazione.Fattura", on_delete=models.CASCADE, related_name="pagamenti_online", verbose_name="fattura")
    fornitore = models.ForeignKey(FornitorePagamento, on_delete=models.SET_NULL, null=True, related_name="pagamenti", verbose_name="fornitore")
    importo = models.DecimalField("importo", max_digits=14, decimal_places=2)
    stato = models.CharField("stato", max_length=8, choices=STATI, default=AVVIATO)
    id_esterno = models.CharField("riferimento del fornitore", max_length=255, blank=True, db_index=True)
    url_pagamento = models.URLField("pagina di pagamento", max_length=1000, blank=True)
    riferimento = models.CharField("pagamento", max_length=255, blank=True, help_text="es. il payment intent di Stripe")
    nota = models.CharField("nota", max_length=300, blank=True)
    creato = models.DateTimeField("avviato il", auto_now_add=True)
    completato_il = models.DateTimeField("pagato il", null=True, blank=True)

    class Meta(AziendaMixin.Meta):
        verbose_name = "pagamento online"
        verbose_name_plural = "pagamenti online"
        ordering = ["-pk"]

    def __str__(self):
        return f"{self.fattura} · {self.importo} €"
