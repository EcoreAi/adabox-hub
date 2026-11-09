from django.apps import AppConfig


class VenditeConfig(AppConfig):
    name = "vendite"
    verbose_name = "Vendite"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("vendite.OrdineVendita", "vendite/_fido_ordine.html", order=2)
        hooks.sezione_dettaglio("vendite.OrdineVendita", "vendite/_risposta.html", order=3)
        hooks.sezione_dettaglio("contatti.Contatto", "vendite/_condizioni_contatto.html", order=24,
                                permission="vendite.view_ordinevendita")
        hooks.sezione_dettaglio("contatti.Contatto", "vendite/_fido_contatto.html", order=25,
                                permission="vendite.view_ordinevendita")
        from django.apps import apps
        if apps.is_installed("crm"):                       # preventivi dalle opportunità, vinta alla conferma
            from . import opportunita
            from .segnali import ordine_confermato
            ordine_confermato.connect(opportunita.vinci, dispatch_uid="vendite.opportunita_vinta")
            hooks.sezione_dettaglio("crm.Opportunita", "vendite/_opportunita_vendite.html", order=10,
                                    permission="vendite.view_ordinevendita")
            hooks.sezione_dettaglio("vendite.OrdineVendita", "vendite/_opportunita_ordine.html", order=1,
                                    permission="crm.view_opportunita")
        if apps.is_installed("portale"):                   # preventivi e ordini nel portale clienti
            from portale import sezioni
            hooks.percorso_portale("/vendite/portale/")
            hooks.percorso_portale("/vendite/preventivo/")       # la risposta al preventivo (stessa pagina del link nell'email)
            sezioni.registra("ordini", "Preventivi e ordini", "vendite:portale_ordini", ordine=10, riepilogo="vendite.portale.riepilogo")
