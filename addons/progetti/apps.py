from django.apps import AppConfig


class ProgettiConfig(AppConfig):
    name = "progetti"
    verbose_name = "Progetti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("progetti.Progetto", "progetti/_compiti.html", order=10)
