from django.apps import AppConfig


class IvaConfig(AppConfig):
    name = "iva"
    verbose_name = "IVA"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks

        from fatturazione import commercialista

        from . import per_commercialista
        commercialista.aggiungi(per_commercialista.liquidazioni)
        hooks.sezione_dettaglio("sdi.FatturaPassiva", "iva/_detraibilita.html", order=3,
                                permission="iva.view_detraibilita")
