from django.db import migrations

TIPI = [("Da fare", "check", 0, 10), ("Chiamata", "user", 1, 20), ("Email", "inbox", 1, 30), ("Riunione", "tool", 3, 40)]


def tipi(apps, schema_editor):
    TipoAttivita = apps.get_model("core", "TipoAttivita")
    for nome, icona, giorni, ordine in TIPI:
        TipoAttivita.objects.get_or_create(nome=nome, defaults={"icona": icona, "giorni": giorni, "ordine": ordine})


class Migration(migrations.Migration):
    dependencies = [("core", "0011_attivita_pianificate")]
    operations = [migrations.RunPython(tipi, migrations.RunPython.noop)]
