from django.db import migrations


def togli_staff(apps, schema_editor):
    """L'admin di Django è solo del ruolo tecnico: chi amministra lavora dal front."""
    User = apps.get_model("auth", "User")
    User.objects.filter(is_superuser=False, profilo__ruolo__amministra=True, profilo__ruolo__tecnico=False).update(is_staff=False)


class Migration(migrations.Migration):
    dependencies = [("core", "0024_catalogo_e_barra")]
    operations = [migrations.RunPython(togli_staff, migrations.RunPython.noop)]
