from django.apps import AppConfig


class FinanziamentiConfig(AppConfig):
    name = "finanziamenti"
    verbose_name = "Finanziamenti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("finanziamenti.Finanziamento", "finanziamenti/_piano.html", order=1)
