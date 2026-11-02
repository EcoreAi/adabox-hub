from django.apps import AppConfig


class CommesseConfig(AppConfig):
    name = "commesse"
    verbose_name = "Commesse"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Estende progetti, ticket e contratti senza modificarli."""
        from django.db.models.signals import post_save, pre_delete

        from core.registry import hooks
        from fatturazione.models import Fattura
        from timesheet.segnali import cronometro_fermato

        from . import operazioni
        hooks.sezione_dettaglio("progetti.Progetto", "commesse/_progetto.html", order=4, permission="commesse.view_condizioni")
        hooks.sezione_dettaglio("helpdesk.Ticket", "commesse/_ticket.html", order=7, permission="timesheet.add_rigaore")
        hooks.sezione_dettaglio("assistenza.Contratto", "commesse/_contratto.html", order=5)
        post_save.connect(operazioni.fattura_cambiata, sender=Fattura, dispatch_uid="commesse.fattura_cambiata")
        pre_delete.connect(operazioni.fattura_eliminata, sender=Fattura, dispatch_uid="commesse.fattura_eliminata")
        cronometro_fermato.connect(operazioni.ore_da_cronometro, dispatch_uid="commesse.cronometro")
