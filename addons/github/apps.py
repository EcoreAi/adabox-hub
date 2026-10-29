from django.apps import AppConfig


class GithubConfig(AppConfig):
    name = "github"
    verbose_name = "GitHub"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("progetti.Compito", "github/_compito.html", order=15,
                                permission="github.view_collegamento")
        hooks.sezione_dettaglio("github.Repository", "github/_webhook.html", order=5)
