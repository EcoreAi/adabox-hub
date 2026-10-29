from django.apps import AppConfig


class ProgettiConfig(AppConfig):
    name = "progetti"
    verbose_name = "Progetti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("progetti.Progetto", "progetti/_compiti.html", order=10)
        hooks.sezione_dettaglio("progetti.Progetto", "progetti/_sviluppo.html", order=12)
        hooks.sezione_dettaglio("progetti.Sprint", "progetti/_sprint.html", order=10)
        hooks.sezione_dettaglio("progetti.Rilascio", "progetti/_rilascio.html", order=10)
        hooks.sezione_dettaglio("progetti.Compito", "progetti/_dipendenze.html", order=10)
        from . import segnali
        segnali.collega_timesheet()
