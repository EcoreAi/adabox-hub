from django.apps import AppConfig


class PrevisioniConfig(AppConfig):
    name = "previsioni"
    verbose_name = 'Previsioni'
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        # il permesso si controlla dentro il riquadro: magazzino e vendite hanno permessi diversi
        hooks.sezione_dettaglio("prodotti.Prodotto", "previsioni/_prodotto.html", order=40, permission=None)
        hooks.widget_dashboard("previsioni.pagine.widget", "previsioni", permission="previsioni.view_previsionepronta")
