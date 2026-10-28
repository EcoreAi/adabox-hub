from django.apps import AppConfig


class DiscussConfig(AppConfig):
    name = "discuss"
    verbose_name = "Discuss"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks

        from . import notifiche  # noqa: F401  (segnale sul chatter)
        hooks.voce_testata("discuss/_campanella.html", order=10, permission="discuss.view_canale")
