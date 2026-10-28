from django.apps import AppConfig


class DocumentiConfig(AppConfig):
    name = "documenti"
    verbose_name = "Documenti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        from . import collegamenti  # noqa: F401  (segnali sugli allegati)
        hooks.sezione_dettaglio("documenti.Documento", "documenti/_scheda_documento.html", order=5)
        hooks.sezione_dettaglio("documenti.Condivisione", "documenti/_condivisione_link.html", order=5)
        hooks.sezione_dettaglio("documenti.Richiesta", "documenti/_richiesta_evadi.html", order=5)
        hooks.sezione_dettaglio("*", "documenti/_documenti_record.html", order=90,
                                permission="documenti.view_documento")
