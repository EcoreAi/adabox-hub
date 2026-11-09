from django.apps import AppConfig


class PersonaleConfig(AppConfig):
    name = "personale"
    verbose_name = "Personale"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from core.registry import hooks
        hooks.sezione_dettaglio("personale.Dipendente", "personale/_saldo.html", order=10)
        hooks.sezione_dettaglio("personale.Dipendente", "personale/_contratti.html", order=11,
                                permission="personale.view_contrattolavoro")
        hooks.sezione_dettaglio("personale.RichiestaModifica", "personale/_decidi_richiesta.html", order=1,
                                permission="personale.change_richiestamodifica")
        from django.db.models.signals import post_save

        from . import contratti
        from .models import ContrattoLavoro
        post_save.connect(contratti.contratto_salvato, sender=ContrattoLavoro, dispatch_uid="personale.contratto_salvato")
        hooks.sezione_dettaglio("personale.Dipendente", "personale/_chiosco_dipendente.html", order=12)
