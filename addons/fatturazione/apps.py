from django.apps import AppConfig


class FatturazioneConfig(AppConfig):
    name = "fatturazione"
    verbose_name = "Fatturazione"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("core.Azienda", "fatturazione/_dati_fiscali_azienda.html", order=10,
                                permission="fatturazione.view_datifiscali")
        hooks.sezione_dettaglio("vendite.OrdineVendita", "fatturazione/_fatture_ordine.html", order=30,
                                permission="fatturazione.view_fattura")
        hooks.sezione_dettaglio("fatturazione.Fattura", "fatturazione/_scadenze.html", order=10)
