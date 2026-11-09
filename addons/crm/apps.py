from django.apps import AppConfig


class CrmConfig(AppConfig):
    name = "crm"
    verbose_name = "CRM"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("crm.ModuloWeb", "crm/_codice_modulo.html", order=5)
        hooks.sezione_dettaglio("crm.Opportunita", "crm/_punteggio.html", order=4)
