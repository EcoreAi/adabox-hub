from django.apps import AppConfig


class SpeseConfig(AppConfig):
    name = "spese"
    verbose_name = "Note spese"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("spese.NotaSpese", "spese/_ricevute.html", order=5)
        from django.apps import apps
        if apps.is_installed("fatturazione"):              # le spese riaddebitate tornano libere se la fattura non vale più
            from django.db.models.signals import post_delete, post_save

            from fatturazione.models import Fattura

            from . import riaddebito
            post_save.connect(riaddebito.fattura_cambiata, sender=Fattura, dispatch_uid="spese.riaddebito.cambiata")
            post_delete.connect(riaddebito.fattura_eliminata, sender=Fattura, dispatch_uid="spese.riaddebito.eliminata")
