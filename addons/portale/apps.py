from django.apps import AppConfig


class PortaleConfig(AppConfig):
    name = "portale"
    label = "portale"
    verbose_name = "Portale clienti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.percorso_portale("/portale/")
        hooks.azione("login", "portale/_accedi_con.html", order=10, pubblica=True)
        hooks.sezione_dettaglio("portale.ProviderAccesso", "portale/_ritorno_provider.html", order=5)
        hooks.sezione_dettaglio("contatti.Contatto", "portale/_contatto.html", order=40, permission="portale.add_accessoportale")
