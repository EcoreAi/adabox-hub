from django.apps import AppConfig


class SharePointConfig(AppConfig):
    name = "sharepoint"
    verbose_name = "SharePoint"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("sharepoint.CollegamentoSharePoint", "sharepoint/_collegamento.html", order=5,
                                permission="sharepoint.view_collegamentosharepoint")
