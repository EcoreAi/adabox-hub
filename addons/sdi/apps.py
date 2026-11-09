from django.apps import AppConfig


class SdiConfig(AppConfig):
    name = "sdi"
    verbose_name = "SDI"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core import blocco
        blocco.registra("sdi.FatturaPassiva", "registrata_il")
        blocco.registra("sdi.PagamentoPassivo", "data", lambda p: p.scadenza.fattura.azienda)
        from core.registry import hooks
        from fatturazione import commercialista

        from . import per_commercialista
        commercialista.aggiungi(per_commercialista.acquisti)
        hooks.sezione_dettaglio("fatturazione.Fattura", "sdi/_sezione_fattura.html", order=20,
                                permission="sdi.view_trasmissione")
