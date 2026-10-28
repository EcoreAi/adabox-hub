from django.apps import AppConfig


class PersonaleConfig(AppConfig):
    name = "personale"
    verbose_name = "Personale"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("personale.Dipendente", "personale/_saldo.html", order=10)
