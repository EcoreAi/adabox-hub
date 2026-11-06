from django.apps import AppConfig


class PagamentiConfig(AppConfig):
    name = "pagamenti"
    verbose_name = "Pagamenti online"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.percorso_portale("/pagamenti/")              # «Paga ora» dal portale clienti ed esito del pagamento
        hooks.sezione_dettaglio("pagamenti.FornitorePagamento", "pagamenti/_fornitore.html", order=5)
        hooks.sezione_dettaglio("fatturazione.Fattura", "pagamenti/_fattura.html", order=15, permission="pagamenti.view_pagamento")
