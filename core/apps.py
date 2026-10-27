from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Core"

    def ready(self):
        from django.conf import settings

        from . import signals  # noqa: F401
        from .viste import registry
        registry.autodiscover(["core", *settings.ADDONS_ATTIVI])
