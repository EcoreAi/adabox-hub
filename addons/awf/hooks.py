"""Hook di installazione di Agentic Workforce (chiamati da manage.py modulo)."""


def post_install(modulo):
    """Elenco delle operazioni con le sole letture predefinite, gruppo «AWF / Agenti» e azienda degli agenti."""
    from core.models import Azienda

    from . import operazioni
    from .models import Collegamento
    operazioni.semina_predefinite()
    operazioni.allinea_gruppo()
    c = Collegamento.attuale()
    if c.azienda is None:
        c.azienda = Azienda.objects.filter(attiva=True).order_by("pk").first()
        c.save(update_fields=["azienda"])


def post_upgrade(modulo, da_versione):
    from . import operazioni
    operazioni.allinea_gruppo()
