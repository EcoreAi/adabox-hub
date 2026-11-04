from django.apps import AppConfig


class DiscussConfig(AppConfig):
    name = "discuss"
    verbose_name = "Discuss"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks

        from . import notifiche  # noqa: F401  (segnale sul chatter)
        hooks.voce_testata("discuss/_campanella.html", order=10, permission="discuss.view_canale")
        hooks.sezione_dettaglio("discuss.Sportello", "discuss/_sportello_codice.html", order=5)
        hooks.azione("core.vista_dettaglio", "discuss/_azioni_record.html", order=20, permission="discuss.add_messaggio")
        from core.chatter import entrata

        from . import posta_canali
        from .models import Canale
        entrata.registra_destinatario(Canale, posta_canali.ricevi_risposta)
        from . import assistente_sito  # noqa: F401  (indice della conoscenza del sito)
