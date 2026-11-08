from django.apps import AppConfig


class AiConfig(AppConfig):
    name = "ai"
    verbose_name = "Assistente AI"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.apps import apps
        from django.db.models.signals import post_delete

        from . import allegati_chat
        from .models import MessaggioChat, ProgettoChat
        from core.registry import hooks
        hooks.sezione_dettaglio("ai.ValutazioneRisposta", "ai/_valutazione.html", order=5)
        hooks.sezione_dettaglio("ai.ProgettoChat", "ai/_progetto.html", order=5)
        hooks.voce_testata("ai/_scrivi_con_ada.html", order=200, permission="ai.add_conversazione")
        hooks.azione("core.vista_dettaglio", "ai/_riassumi_record.html", order=15, permission="ai.add_conversazione")
        hooks.sezione_dettaglio("*", "ai/_progetti_record.html", order=950, permission="ai.view_progettochat")
        hooks.sezione_dettaglio("ai.ServerMCP", "ai/_server_mcp.html", order=5, permission="ai.change_servermcp")
        hooks.sezione_dettaglio("ai.Provider", "ai/_provider_catalogo.html", order=5, permission="ai.view_modello")
        post_delete.connect(allegati_chat.togli_file, sender=MessaggioChat, dispatch_uid="ai.togli_allegati")
        post_delete.connect(allegati_chat.togli_file, sender=ProgettoChat, dispatch_uid="ai.togli_file_progetto")
        from django.db.models.signals import pre_delete
        pre_delete.connect(_chat_all_area_personale, sender=ProgettoChat, dispatch_uid="ai.chat_area_personale")
        if apps.is_installed("documenti"):
            from . import segnali
            segnali.collega_documenti()


def _chat_all_area_personale(sender, instance, **kwargs):
    """Un'area condivisa che si elimina: le sue chat tornano nell'area personale di chi le ha scritte."""
    if instance.personale:
        return
    from .aree import riaccogli
    from .models import Conversazione
    riaccogli(Conversazione.objects.filter(progetto=instance))
