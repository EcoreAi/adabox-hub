from django.apps import AppConfig


class TimesheetConfig(AppConfig):
    name = "timesheet"
    verbose_name = "Timesheet"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Estende progetti senza modificarlo: sezioni Ore nei dettagli di progetto e compito."""
        from core.registry import hooks
        hooks.sezione_dettaglio("progetti.Progetto", "timesheet/_ore_progetto.html", order=20,
                                permission="timesheet.view_rigaore")
        hooks.sezione_dettaglio("progetti.Compito", "timesheet/_ore_compito.html", order=20,
                                permission="timesheet.view_rigaore")
