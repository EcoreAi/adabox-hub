from django.apps import AppConfig


class AgateConfig(AppConfig):
    name = "agate"
    verbose_name = "Agate"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from ai import proposte

        from .guardia import guardia
        proposte.registra_guardia(guardia)
