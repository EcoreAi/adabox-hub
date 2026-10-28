from django.apps import AppConfig


class DocumentiConfig(AppConfig):
    name = "documenti"
    verbose_name = "Documenti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("documenti.Documento", "documenti/_scheda_documento.html", order=5)
