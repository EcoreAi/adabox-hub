from django.apps import AppConfig


class ConnettoriConfig(AppConfig):
    name = "connettori"
    verbose_name = "Connettori"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from core.registry import hooks

        from . import eventi
        post_save.connect(eventi.salvato, dispatch_uid="connettori.salvato")
        post_delete.connect(eventi.eliminato, dispatch_uid="connettori.eliminato")
        hooks.sezione_dettaglio("connettori.Webhook", "connettori/_webhook.html", order=5, permission="connettori.change_webhook")
