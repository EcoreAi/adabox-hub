from django.apps import AppConfig


class PrivacyConfig(AppConfig):
    name = "privacy"
    verbose_name = "Privacy"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks

        from . import conservazione
        conservazione.registra_predefiniti()
        hooks.sezione_dettaglio("contatti.Contatto", "privacy/_contatto.html", order=45, permission="privacy.view_consenso")
