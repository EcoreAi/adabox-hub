from django.apps import AppConfig


class ContattiConfig(AppConfig):
    name = "contatti"
    verbose_name = "Contatti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("contatti.Contatto", "contatti/_persone.html", order=10)
