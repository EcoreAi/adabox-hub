from django.apps import AppConfig


class StudioConfig(AppConfig):
    name = "studio"
    verbose_name = "Studio"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.viste import personalizza

        from . import servizi
        personalizza.registra(servizi.per_vista)
