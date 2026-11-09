from django.apps import AppConfig


class FlottaConfig(AppConfig):
    name = "flotta"
    verbose_name = "Parco auto"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("flotta.Veicolo", "flotta/_veicolo.html", order=1)
        hooks.sezione_dettaglio("personale.Dipendente", "flotta/_dipendente.html", order=30, permission="flotta.view_veicolo")
