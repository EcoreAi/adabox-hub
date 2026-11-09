from django.apps import AppConfig


class FatturazioneConfig(AppConfig):
    name = "fatturazione"
    verbose_name = "Fatturazione"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core import blocco
        blocco.registra("fatturazione.Fattura", "data")
        blocco.registra("fatturazione.Incasso", "data", lambda i: i.scadenza.fattura.azienda)
        blocco.registra("fatturazione.CreditoCliente", "data")
        from core.registry import hooks
        from vendite.segnali import ordine_annullato

        from . import operazioni
        ordine_annullato.connect(operazioni.annulla_da_ordine, dispatch_uid="fatturazione.annulla_da_ordine")
        hooks.sezione_dettaglio("core.Azienda", "fatturazione/_dati_fiscali_azienda.html", order=10,
                                permission="fatturazione.view_datifiscali")
        hooks.sezione_dettaglio("vendite.OrdineVendita", "fatturazione/_fatture_ordine.html", order=30,
                                permission="fatturazione.view_fattura")
        hooks.sezione_dettaglio("fatturazione.Fattura", "fatturazione/_scadenze.html", order=10)
        hooks.sezione_dettaglio("contatti.Contatto", "fatturazione/_posizione_contatto.html", order=40,
                                permission="fatturazione.view_fattura")
        from django.apps import apps
        if apps.is_installed("portale"):                   # le fatture nel portale clienti
            from portale import sezioni
            hooks.percorso_portale("/fatturazione/portale/")
            sezioni.registra("fatture", "Fatture", "fatturazione:portale_fatture", ordine=20, riepilogo="fatturazione.portale.riepilogo")
