from django.apps import AppConfig


class QualitaConfig(AppConfig):
    name = "qualita"
    verbose_name = "Qualità"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks

        from . import segnali  # noqa: F401  (casi del progetto aggiunti ai collaudi nuovi)
        hooks.sezione_dettaglio("qualita.Collaudo", "qualita/_collaudo.html", order=5)
        hooks.sezione_dettaglio("progetti.Rilascio", "qualita/_rilascio.html", order=20,
                                permission="qualita.view_collaudo")
        hooks.sezione_dettaglio("progetti.Compito", "qualita/_difetto.html", order=20,
                                permission="qualita.view_collaudo")
