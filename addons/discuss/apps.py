from django.apps import AppConfig


class DiscussConfig(AppConfig):
    name = "discuss"
    verbose_name = "Discuss"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks

        from . import notifiche  # noqa: F401  (segnale sul chatter)
        hooks.voce_testata("discuss/_campanella.html", order=10, permission="discuss.view_canale")
        hooks.sezione_dettaglio("discuss.ModelloWhatsApp", "discuss/_modello_stato.html", order=5)
        hooks.sezione_dettaglio("discuss.Connessione", "discuss/_connessione_guida.html", order=5)
        hooks.sezione_dettaglio("discuss.Sportello", "discuss/_sportello_codice.html", order=5)
        hooks.sezione_dettaglio("contatti.Contatto", "discuss/_chat_del_contatto.html", order=35, permission="discuss.view_canale")
        hooks.azione("core.vista_dettaglio", "discuss/_azioni_record.html", order=20, permission="discuss.add_messaggio")
        from core.chatter import entrata

        from . import posta_canali
        from .models import Canale
        entrata.registra_destinatario(Canale, posta_canali.ricevi_risposta)
        from . import assistente_sito  # noqa: F401  (indice della conoscenza del sito)
        from django.apps import apps
        if apps.is_installed("portale"):
            hooks.percorso_portale("/discuss/portale/")         # solo l'assistente: il resto di Discuss resta chiuso ai clienti
            from portale import sezioni
            sezioni.registra("assistente", "Assistente", "discuss:portale_assistente", ordine=5,
                             visibile="discuss.portale_assistente.visibile")
        if apps.is_installed("wiki"):
            from . import conoscenza_wiki
            conoscenza_wiki.collega()
            hooks.sezione_dettaglio("wiki.PaginaWiki", "discuss/_wiki_pubblica.html", order=1)
            hooks.sezione_dettaglio("wiki.SpazioWiki", "discuss/_wiki_pubblica.html", order=1)
