from django.apps import AppConfig


class CassaConfig(AppConfig):
    name = "cassa"
    verbose_name = "Cassa"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_save, pre_delete

        from core.registry import hooks
        from fatturazione.models import Incasso

        from . import operazioni
        hooks.sezione_dettaglio("cassa.Cassa", "cassa/_movimenti.html", order=1)
        post_save.connect(operazioni.incasso_salvato, sender=Incasso, dispatch_uid="cassa.incasso_salvato")
        pre_delete.connect(operazioni.incasso_eliminato, sender=Incasso, dispatch_uid="cassa.incasso_eliminato")
