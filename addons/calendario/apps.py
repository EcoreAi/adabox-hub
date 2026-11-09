from django.apps import AppConfig


class CalendarioConfig(AppConfig):
    name = "calendario"
    verbose_name = "Calendario"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("calendario.TipoAppuntamento", "calendario/_link_prenotazione.html", order=5)
