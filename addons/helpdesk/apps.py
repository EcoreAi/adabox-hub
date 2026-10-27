from django.apps import AppConfig


class HelpdeskConfig(AppConfig):
    name = "helpdesk"
    verbose_name = "Helpdesk"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.chatter import entrata

        from .email import apri_ticket
        entrata.registra_gestore(apri_ticket)
