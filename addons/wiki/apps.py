from django.apps import AppConfig


class WikiConfig(AppConfig):
    name = "wiki"
    verbose_name = "Wiki"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("wiki.PaginaWiki", "wiki/_pagina.html", order=0)
        from django.apps import apps
        if apps.is_installed("ai"):
            from ai import conoscenza

            from . import servizi
            conoscenza.registra_senza_risultati("wiki", servizi.domanda_senza_risposta)
