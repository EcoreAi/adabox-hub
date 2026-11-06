from django.apps import AppConfig


class AwfConfig(AppConfig):
    name = "awf"
    verbose_name = "Agentic Workforce"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import segnali  # noqa: F401  (accesso negato agli agenti, eventi alla fabbrica, permessi)
