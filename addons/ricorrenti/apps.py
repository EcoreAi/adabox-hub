from django.apps import AppConfig


class RicorrentiConfig(AppConfig):
    name = "ricorrenti"
    verbose_name = "Contratti ricorrenti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import pre_delete

        from core.registry import hooks
        from fatturazione.models import Fattura

        from . import operazioni
        hooks.sezione_dettaglio("ricorrenti.Canone", "ricorrenti/_periodi.html", order=4)
        pre_delete.connect(operazioni.fattura_eliminata, sender=Fattura, dispatch_uid="ricorrenti.fattura_eliminata")
