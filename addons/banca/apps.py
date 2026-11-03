from django.apps import AppConfig


class BancaConfig(AppConfig):
    name = "banca"
    verbose_name = "Banca"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_delete

        from core.registry import hooks

        from . import abbina
        from .models import Abbinamento
        hooks.sezione_dettaglio("banca.MovimentoBanca", "banca/_movimento.html", order=2)
        post_delete.connect(abbina.abbinamento_tolto, sender=Abbinamento, dispatch_uid="banca.abbinamento_tolto")
