from django.apps import AppConfig


class AutomazioniConfig(AppConfig):
    name = "automazioni"
    verbose_name = "Automazioni"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        """Ascolta i modelli del catalogo: quelli dei moduli installati, senza che i moduli sappiano di essere osservati."""
        from django.db.models.signals import post_save, pre_save

        from django.db.models.signals import post_delete

        from . import catalogo, motore
        from .models import Regola
        post_save.connect(motore.dimentica_cache, sender=Regola, dispatch_uid="automazioni.cache_salva")
        post_delete.connect(motore.dimentica_cache, sender=Regola, dispatch_uid="automazioni.cache_elimina")
        for modello in catalogo.modelli_osservati():
            uid = modello._meta.label_lower
            pre_save.connect(motore.prima_di_salvare, sender=modello, dispatch_uid=f"automazioni.pre.{uid}")
            post_save.connect(motore.dopo_il_salvataggio, sender=modello, dispatch_uid=f"automazioni.post.{uid}")
