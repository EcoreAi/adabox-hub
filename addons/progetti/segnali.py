"""Segnali dei Progetti per gli altri moduli e avvisi di budget dalle ore del timesheet."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import Signal

rilascio_pubblicato = Signal()                  # rilascio, utente: un rilascio è stato pubblicato

SOGLIE = (80, 100)


def controlla_budget(progetto):
    """Nota nel chatter del progetto la prima volta che le ore consumate superano l'80% e il 100% del budget;
    se le ore scendono sotto una soglia (righe corrette o eliminate) l'avviso potrà ripartire."""
    from core import chatter
    b = progetto.budget()
    percentuale = b[2] if b else 0
    raggiunta = max((s for s in SOGLIE if percentuale >= s), default=0)
    if raggiunta == progetto.budget_avvisato:
        return
    type(progetto).objects.filter(pk=progetto.pk).update(budget_avvisato=raggiunta)
    if raggiunta > progetto.budget_avvisato:
        testo = ("Budget di ore superato" if raggiunta >= 100 else "Budget di ore quasi esaurito")
        chatter.scrivi(progetto, None, f"{testo}: {b[1]:g} ore su {b[0]:g} ({percentuale}%).", tipo="nota")
    progetto.budget_avvisato = raggiunta


def _ore_cambiate(sender, instance, raw=False, **_):
    if not raw and instance.progetto_id:
        controlla_budget(instance.progetto)


def collega_timesheet():
    from django.apps import apps
    if not apps.is_installed("timesheet"):
        return
    RigaOre = apps.get_model("timesheet", "RigaOre")
    post_save.connect(_ore_cambiate, sender=RigaOre, dispatch_uid="progetti.budget_ore_salvate")
    post_delete.connect(_ore_cambiate, sender=RigaOre, dispatch_uid="progetti.budget_ore_eliminate")
