from django.apps import AppConfig


class AiConfig(AppConfig):
    name = "ai"
    verbose_name = "Assistente AI"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import post_delete

        from . import allegati_chat
        from .models import MessaggioChat
        from core.registry import hooks
        hooks.sezione_dettaglio("ai.ValutazioneRisposta", "ai/_valutazione.html", order=5)
        post_delete.connect(allegati_chat.togli_file, sender=MessaggioChat, dispatch_uid="ai.togli_allegati")
        if apps.is_installed("documenti"):
            from . import segnali
            segnali.collega_documenti()
