from django.apps import AppConfig, apps


class ConnettoriConfig(AppConfig):
    name = "connettori"
    verbose_name = "Connettori"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from core.registry import hooks

        from core import esterni, regole

        from . import eventi, visibilita
        regole.registra_filtro(visibilita.filtro)            # i dati di Odoo per utente: solo a chi li vede là
        esterni.registra(visibilita.gestito_da)              # gli ordini di Odoo: sola lettura, consegne e fatture a Odoo
        hooks.sezione_dettaglio("vendite.OrdineVendita", "connettori/_gestito_fuori.html", order=0)
        post_save.connect(eventi.salvato, dispatch_uid="connettori.salvato")
        post_delete.connect(eventi.eliminato, dispatch_uid="connettori.eliminato")
        hooks.sezione_dettaglio("connettori.Webhook", "connettori/_webhook.html", order=5, permission="connettori.change_webhook")
        hooks.sezione_dettaglio("connettori.CollegamentoEsterno", "connettori/_collegamento.html", order=5, permission="connettori.view_collegamentoesterno")
        if apps.is_installed("contatti"):
            from contatti.models import Contatto

            from . import sincronia
            post_save.connect(sincronia.contatto_salvato, sender=Contatto, dispatch_uid="connettori.contatto_salvato")
        if apps.is_installed("crm"):
            from crm.models import Opportunita

            from . import sincronia
            post_save.connect(sincronia.opportunita_salvata, sender=Opportunita, dispatch_uid="connettori.opportunita_salvata")
