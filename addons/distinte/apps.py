from django.apps import AppConfig


class DistinteConfig(AppConfig):
    name = "distinte"
    verbose_name = "Distinte di pagamento"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("distinte.Distinta", "distinte/_distinta.html", order=1)
        hooks.sezione_dettaglio("banca.Conto", "distinte/_conto.html", order=5, permission="distinte.view_configconto")
        hooks.sezione_dettaglio("contatti.Contatto", "distinte/_coordinate.html", order=40,
                                permission="distinte.view_coordinatebancarie")
