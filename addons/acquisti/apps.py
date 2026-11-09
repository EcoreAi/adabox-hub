from django.apps import AppConfig, apps


class AcquistiConfig(AppConfig):
    name = "acquisti"
    verbose_name = "Acquisti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("acquisti.OrdineAcquisto", "acquisti/_approvazioni.html", order=5)
        hooks.sezione_dettaglio("acquisti.OrdineAcquisto", "acquisti/_riscontro.html", order=10)
        hooks.sezione_dettaglio("acquisti.Gara", "acquisti/_confronto.html", order=5)
        hooks.sezione_dettaglio("acquisti.ContrattoQuadro", "acquisti/_residui.html", order=5)
        hooks.sezione_dettaglio("contatti.Contatto", "acquisti/_fornitore.html", order=30,
                                permission="acquisti.view_vocelistino")
        hooks.sezione_dettaglio("prodotti.Prodotto", "acquisti/_prodotto.html", order=30,
                                permission="acquisti.view_vocelistino")
        if apps.is_installed("sdi"):                    # lo SDI è facoltativo: senza, le fatture non si collegano
            from django.db.models.signals import post_delete
            from sdi.models import FatturaPassiva
            from sdi.segnali import fattura_ricevuta

            from . import riscontro
            fattura_ricevuta.connect(riscontro.fattura_ricevuta, dispatch_uid="acquisti.fattura_ricevuta")
            from sdi.segnali import registrazione
            registrazione.connect(riscontro.blocca_registrazione, dispatch_uid="acquisti.blocca_registrazione")
            post_delete.connect(riscontro.fattura_eliminata, sender=FatturaPassiva, dispatch_uid="acquisti.fattura_eliminata")
            hooks.sezione_dettaglio("sdi.FatturaPassiva", "acquisti/_fattura_ordini.html", order=10,
                                    permission="acquisti.view_ordineacquisto")
