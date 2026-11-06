from django.apps import AppConfig


class CapacitaConfig(AppConfig):
    name = "capacita"
    verbose_name = "Capacità e consegne"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("progetti.Progetto", "capacita/_progetto.html", order=3, permission="capacita.view_capacita")
