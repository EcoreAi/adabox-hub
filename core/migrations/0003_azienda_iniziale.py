from django.conf import settings
from django.db import migrations


def azienda_iniziale(apps, schema_editor):
    """Prima azienda dal brand e profilo per gli utenti già esistenti.
    Niente pk esplicito: su Postgres non farebbe avanzare la sequenza."""
    Azienda = apps.get_model("core", "Azienda")
    ProfiloUtente = apps.get_model("core", "ProfiloUtente")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    if not Azienda.objects.exists():
        Azienda.objects.create(nome=getattr(settings, "THEME", {}).get("brand", "Azienda"))
    attive = list(Azienda.objects.filter(attiva=True).order_by("nome"))
    for utente in User.objects.all():
        profilo, creato = ProfiloUtente.objects.get_or_create(utente=utente)
        if creato:
            profilo.aziende.set(attive)
            profilo.azienda_predefinita = attive[0] if attive else None
            profilo.save()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_kernel"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(azienda_iniziale, migrations.RunPython.noop)]
