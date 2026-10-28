from django.apps import AppConfig


class SpeseConfig(AppConfig):
    name = "spese"
    verbose_name = "Note spese"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("spese.NotaSpese", "spese/_ricevute.html", order=5)
