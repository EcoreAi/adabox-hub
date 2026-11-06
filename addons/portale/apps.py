from django.apps import AppConfig


class PortaleConfig(AppConfig):
    name = "portale"
    label = "portale"
    verbose_name = "Portale clienti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.percorso_portale("/portale/")
        hooks.sezione_dettaglio("contatti.Contatto", "portale/_contatto.html", order=40, permission="portale.add_accessoportale")
