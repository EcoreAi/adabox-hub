from django.apps import AppConfig


class SdiConfig(AppConfig):
    name = "sdi"
    verbose_name = "SDI"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("fatturazione.Fattura", "sdi/_sezione_fattura.html", order=20,
                                permission="sdi.view_trasmissione")
