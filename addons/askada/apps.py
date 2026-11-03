from django.apps import AppConfig


class AskadaConfig(AppConfig):
    name = "askada"
    verbose_name = "Chiedi ad Ada"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.voce_testata("askada/_widget.html", order=95, permission="askada.add_domanda")
