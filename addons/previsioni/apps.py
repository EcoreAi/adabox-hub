from django.apps import AppConfig


class PrevisioniConfig(AppConfig):
    name = "previsioni"
    verbose_name = 'Previsioni'
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("prodotti.Prodotto", "previsioni/_prodotto.html", order=40,
                                permission="previsioni.view_previsionearticolo")
