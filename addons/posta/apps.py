from django.apps import AppConfig


class PostaConfig(AppConfig):
    name = "posta"
    verbose_name = "Posta e calendario"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.db.models.signals import post_save

        from calendario.models import Evento

        from . import agenda
        post_save.connect(agenda.evento_salvato, sender=Evento, dispatch_uid="posta.evento_salvato")
