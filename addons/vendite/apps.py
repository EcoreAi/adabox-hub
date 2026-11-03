from django.apps import AppConfig


class VenditeConfig(AppConfig):
    name = "vendite"
    verbose_name = "Vendite"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("vendite.OrdineVendita", "vendite/_risposta.html", order=3)
