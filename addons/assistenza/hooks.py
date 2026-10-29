"""Hook di installazione dell'assistenza: una politica SLA di partenza."""


def post_install(modulo):
    from .models import PoliticaSLA
    PoliticaSLA.objects.get_or_create(nome="Standard", defaults={
        "risposta_urgente": 1, "risposta_alta": 4, "risposta_media": 8, "risposta_bassa": 16,
        "risoluzione_urgente": 8, "risoluzione_alta": 24, "risoluzione_media": 40, "risoluzione_bassa": 80})
