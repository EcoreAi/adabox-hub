from django.apps import AppConfig


class WikiConfig(AppConfig):
    name = "wiki"
    verbose_name = "Wiki"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("wiki.PaginaWiki", "wiki/_pagina.html", order=0)
