from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Core"

    def ready(self):
        from django.conf import settings

        from django.db.models.signals import post_migrate

        from . import cron, signals  # noqa: F401
        post_migrate.connect(cron.sincronizza, sender=self, dispatch_uid="core.cron")
        from . import ruoli
        post_migrate.connect(ruoli.aggiorna_piattaforma, sender=self, dispatch_uid="core.piattaforma")
        from .viste import registry
        registry.autodiscover(["core", *settings.ADDONS_ATTIVI])
        from . import registro
        registro.collega()
        from .registry import hooks
        hooks.sezione_dettaglio("core.ModelloStampa", "core/_anteprima_stampa.html", order=5)
        hooks.sezione_dettaglio("core.Azienda", "core/_periodo_chiuso.html", order=5)
        hooks.sezione_dettaglio("*", "core/_approvazioni_record.html", order=3)
