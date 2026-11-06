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
        from django.apps import apps
        if not apps.is_installed("portale"):               # prima dell'aggiornamento che installa il portale
            return
        hooks.percorso_portale("/assistenza/portale/")
        from portale import sezioni
        sezioni.registra("richieste", "Richieste", "assistenza:portale", ordine=40, riepilogo="assistenza.portale.riepilogo_richieste",
                         attive=["portale_ticket", "portale_nuovo"])
        sezioni.registra("progetti", "Progetti", "assistenza:portale_progetti", ordine=50, riepilogo="assistenza.portale.riepilogo_progetti")
        sezioni.registra("guida", "Guida", "assistenza:portale_guida", ordine=60, attive=["portale_articolo"])
