from django.apps import AppConfig


class AssistenzaConfig(AppConfig):
    name = "assistenza"
    verbose_name = "Assistenza clienti"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks

        from . import segnali, sviluppo  # noqa: F401  (instradamento, SLA, prima risposta, compiti chiusi)
        hooks.sezione_dettaglio("helpdesk.Ticket", "assistenza/_ticket.html", order=5,
                                permission="assistenza.view_datiticket")
        hooks.sezione_dettaglio("progetti.Progetto", "assistenza/_progetto.html", order=5,
                                permission="assistenza.view_supporto")
        hooks.sezione_dettaglio("assistenza.Supporto", "assistenza/_widget.html", order=5)
        hooks.sezione_dettaglio("contatti.Contatto", "assistenza/_portale_contatto.html", order=40,
                                permission="assistenza.add_accessoportale")
