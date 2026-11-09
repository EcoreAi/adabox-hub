from django.apps import AppConfig, apps


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
        hooks.sezione_dettaglio("connettori.CollegamentoEsterno", "connettori/_collegamento.html", order=5, permission="connettori.view_collegamentoesterno")
        if apps.is_installed("contatti"):
            from contatti.models import Contatto

            from . import sincronia
            post_save.connect(sincronia.contatto_salvato, sender=Contatto, dispatch_uid="connettori.contatto_salvato")
        if apps.is_installed("crm"):
            from crm.models import Opportunita

            from . import sincronia
            post_save.connect(sincronia.opportunita_salvata, sender=Opportunita, dispatch_uid="connettori.opportunita_salvata")
