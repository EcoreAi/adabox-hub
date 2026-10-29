from django.apps import AppConfig


class AiConfig(AppConfig):
    name = "ai"
    verbose_name = "Assistente AI"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.apps import apps
        if apps.is_installed("documenti"):
            from . import segnali
            segnali.collega_documenti()
