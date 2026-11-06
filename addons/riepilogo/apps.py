from django.apps import AppConfig


class RiepilogoConfig(AppConfig):
    name = "riepilogo"
    verbose_name = "Riepilogo giornaliero"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        from core.registry import hooks

        from . import accessi
        hooks.voce_testata("riepilogo/_icona.html", order=5, permission="riepilogo.view_preferenza")
        user_logged_in.connect(accessi.registra, dispatch_uid="riepilogo.accesso")
