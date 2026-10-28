from django.apps import AppConfig, apps


class MagazzinoConfig(AppConfig):
    name = "magazzino"
    verbose_name = "Magazzino"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Collegamenti con vendite e acquisti, solo se sono installati: il magazzino non ne dipende."""
        from core.registry import hooks

        from . import collegamenti
        if apps.is_installed("vendite"):
            from vendite.segnali import ordine_confermato
            ordine_confermato.connect(collegamenti.consegna_da_ordine, dispatch_uid="magazzino.consegna")
            hooks.sezione_dettaglio("vendite.OrdineVendita", "magazzino/_consegne_ordine.html", order=20,
                                    permission="magazzino.view_consegna")
        if apps.is_installed("acquisti"):
            from acquisti.segnali import ordine_acquisto_confermato
            ordine_acquisto_confermato.connect(collegamenti.ricevimento_da_ordine, dispatch_uid="magazzino.ricevimento")
            hooks.sezione_dettaglio("acquisti.OrdineAcquisto", "magazzino/_ricevimenti_ordine.html", order=20,
                                    permission="magazzino.view_ricevimento")
