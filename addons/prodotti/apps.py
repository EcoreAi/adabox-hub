from django.apps import AppConfig


class ProdottiConfig(AppConfig):
    name = "prodotti"
    verbose_name = "Prodotti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("prodotti.Prodotto", "prodotti/_varianti.html", order=5)
