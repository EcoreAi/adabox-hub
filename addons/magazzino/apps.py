from django.apps import AppConfig, apps


class MagazzinoConfig(AppConfig):
    name = "magazzino"
    verbose_name = "Magazzino"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Collegamenti con vendite e acquisti, solo se sono installati: il magazzino non ne dipende."""
        from core.registry import hooks

        from django.db.models.signals import post_save

        from . import collegamenti
        from .models import Movimento
        post_save.connect(_movimento_creato, sender=Movimento, dispatch_uid="magazzino.costi")
        hooks.sezione_dettaglio("magazzino.Ubicazione", "magazzino/_contenuto_ubicazione.html", order=5)
        hooks.sezione_dettaglio("magazzino.Lotto", "magazzino/_tracciabilita.html", order=5)
        hooks.sezione_dettaglio("prodotti.Prodotto", "magazzino/_costo_prodotto.html", order=30,
                                permission="magazzino.view_movimento")
        hooks.sezione_dettaglio("prodotti.Prodotto", "magazzino/_kit_prodotto.html", order=25,
                                permission="magazzino.view_movimento")
        if apps.is_installed("fatturazione"):
            from fatturazione import commercialista

            from . import per_commercialista
            commercialista.aggiungi(per_commercialista.inventario)
        if apps.is_installed("vendite"):
            from vendite.segnali import ordine_annullato, ordine_confermato
            ordine_confermato.connect(collegamenti.consegna_da_ordine, dispatch_uid="magazzino.consegna")
            ordine_annullato.connect(collegamenti.annulla_consegne, dispatch_uid="magazzino.annulla_consegne")
            hooks.sezione_dettaglio("vendite.OrdineVendita", "magazzino/_consegne_ordine.html", order=20,
                                    permission="magazzino.view_consegna")
        if apps.is_installed("acquisti"):
            from acquisti.segnali import ordine_acquisto_annullato, ordine_acquisto_confermato
            ordine_acquisto_confermato.connect(collegamenti.ricevimento_da_ordine, dispatch_uid="magazzino.ricevimento")
            ordine_acquisto_annullato.connect(collegamenti.annulla_ricevimenti, dispatch_uid="magazzino.annulla_ricevimenti")
            hooks.sezione_dettaglio("acquisti.OrdineAcquisto", "magazzino/_ricevimenti_ordine.html", order=20,
                                    permission="magazzino.view_ricevimento")


def _movimento_creato(sender, instance, created, raw=False, **kwargs):
    """Ogni movimento nuovo riallinea i costi del prodotto (anche se arriva dall'API o da un altro modulo)."""
    if created and not raw:
        from . import costi
        costi.ricalcola(instance.prodotto)
