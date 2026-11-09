from django.apps import AppConfig


class AnaliticaConfig(AppConfig):
    name = "analitica"
    verbose_name = "Analitica"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.apps import apps

        from core.registry import hooks
        hooks.sezione_dettaglio("fatturazione.Fattura", "analitica/_documento.html", order=40, permission="analitica.view_imputazione")
        hooks.sezione_dettaglio("analitica.Budget", "analitica/_budget.html", order=1)
        if apps.is_installed("sdi"):
            hooks.sezione_dettaglio("sdi.FatturaPassiva", "analitica/_documento.html", order=40, permission="analitica.view_imputazione")
        if apps.is_installed("spese"):
            hooks.sezione_dettaglio("spese.NotaSpese", "analitica/_documento.html", order=40, permission="analitica.view_imputazione")
