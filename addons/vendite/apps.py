from django.apps import AppConfig


class VenditeConfig(AppConfig):
    name = "vendite"
    verbose_name = "Vendite"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("vendite.OrdineVendita", "vendite/_fido_ordine.html", order=2)
        hooks.sezione_dettaglio("vendite.OrdineVendita", "vendite/_risposta.html", order=3)
        hooks.sezione_dettaglio("vendite.OrdineVendita", "vendite/_modello.html", order=4, permission="vendite.change_ordinevendita")
        hooks.sezione_dettaglio("contatti.Contatto", "vendite/_condizioni_contatto.html", order=24,
                                permission="vendite.view_ordinevendita")
        hooks.sezione_dettaglio("contatti.Contatto", "vendite/_fido_contatto.html", order=25,
                                permission="vendite.view_ordinevendita")
        from django.apps import apps
        from . import provvigioni
        from .segnali import ordine_annullato, ordine_confermato
        ordine_confermato.connect(provvigioni.da_conferma, dispatch_uid="vendite.provvigioni")
        ordine_annullato.connect(provvigioni.da_annullamento, dispatch_uid="vendite.provvigioni_annullate")
        if apps.is_installed("fatturazione"):              # provvigioni che maturano all'incasso
            from django.db.models.signals import post_delete, post_save
            incasso = apps.get_model("fatturazione", "Incasso")
            post_save.connect(provvigioni.da_incasso, sender=incasso, dispatch_uid="vendite.provvigioni_incasso")
            post_delete.connect(provvigioni.incasso_eliminato, sender=incasso, dispatch_uid="vendite.provvigioni_incasso_eliminato")
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
