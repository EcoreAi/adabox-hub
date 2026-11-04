from django.apps import AppConfig


class GraficiConfig(AppConfig):
    name = "grafici"
    verbose_name = "Analisi"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dashboard("grafici/_schede.html", order=10, permission="grafici.view_pagina")
        hooks.azione("ai.artifact", "grafici/_salva_artifact.html", permission="grafici.add_grafico")
        hooks.azione("core.vista_grafico", "grafici/_salva_vista.html", permission="grafici.add_grafico")
