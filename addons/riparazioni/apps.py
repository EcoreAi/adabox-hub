from django.apps import AppConfig


class RiparazioniConfig(AppConfig):
    name = "riparazioni"
    verbose_name = "Riparazioni"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("riparazioni.Riparazione", "riparazioni/_riparazione.html", order=1)
