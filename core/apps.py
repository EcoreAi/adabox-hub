from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Core"

    def ready(self):
        from django.conf import settings

        from django.db.models.signals import post_migrate

        from . import cron, signals  # noqa: F401
        post_migrate.connect(cron.sincronizza, sender=self, dispatch_uid="core.cron")
        from .viste import registry
        registry.autodiscover(["core", *settings.ADDONS_ATTIVI])
