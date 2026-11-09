from django.apps import AppConfig


class GraficiConfig(AppConfig):
    name = "grafici"
    verbose_name = "Analisi"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dashboard("grafici/_schede.html", order=10, permission="grafici.view_pagina")
        hooks.parte_della_dashboard("grafici")           # le pagine sono schede della Dashboard, non un'app della barra
        hooks.widget_dashboard("grafici.motore.widget_per_panoramica", "grafici", permission="grafici.view_grafico")
        hooks.azione("core.dashboard_cassetto", "grafici/_cassetto_azioni.html", permission="grafici.add_grafico")
        hooks.azione("ai.artifact", "grafici/_salva_artifact.html", permission="grafici.add_grafico")
        hooks.azione("core.vista_grafico", "grafici/_salva_vista.html", permission="grafici.add_grafico")
        from core import report_pianificati

        from . import stampa
        report_pianificati.registra_tipo("analisi", "Una pagina di Analisi", stampa.genera, stampa.scelte, formati=("pdf",))
