"""Gli accessi al portale passano al modulo «portale» (2026-11-06): si copiano nella sua tabella, con i permessi di chi
poteva invitare e le email d'invito personalizzate, e poi il vecchio modello si elimina."""
from django.conf import settings
from django.db import migrations

AZIONI = ("add", "change", "delete", "view")


def copia(apps, schema_editor):
    Vecchio = apps.get_model("assistenza", "AccessoPortale")
    Nuovo = apps.get_model("portale", "AccessoPortale")
    for a in Vecchio.objects.all():
        nuovo, _ = Nuovo.objects.get_or_create(utente_id=a.utente_id, defaults={"contatto_id": a.contatto_id, "invitato_da_id": a.invitato_da_id})
        Nuovo.objects.filter(pk=nuovo.pk).update(invitato_il=a.invitato_il)          # auto_now_add: si rimette la data vera
    ModelloEmail = apps.get_model("core", "ModelloEmail")
    ModelloEmail.objects.filter(codice="assistenza.invito").update(codice="portale.invito")
    # chi poteva invitare o sospendere dal portale (gruppi e utenti) lo può ancora: i permessi passano a «portale»
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    vecchio_ct = ContentType.objects.filter(app_label="assistenza", model="accessoportale").first()
    if vecchio_ct is None:
        return
    nuovo_ct, _ = ContentType.objects.get_or_create(app_label="portale", model="accessoportale")
    for azione in AZIONI:
        vecchio = Permission.objects.filter(content_type=vecchio_ct, codename=f"{azione}_accessoportale").first()
        if vecchio is None:
            continue
        nuovo, _ = Permission.objects.get_or_create(content_type=nuovo_ct, codename=f"{azione}_accessoportale",
                                                    defaults={"name": vecchio.name})
        for g in Group.objects.filter(permissions=vecchio):
            g.permissions.add(nuovo)
        for u in User.objects.filter(user_permissions=vecchio):
            u.user_permissions.add(nuovo)


def indietro(apps, schema_editor):
    Vecchio = apps.get_model("assistenza", "AccessoPortale")
    Nuovo = apps.get_model("portale", "AccessoPortale")
    for a in Nuovo.objects.all():
        Vecchio.objects.get_or_create(utente_id=a.utente_id, defaults={"contatto_id": a.contatto_id, "invitato_da_id": a.invitato_da_id})
    apps.get_model("core", "ModelloEmail").objects.filter(codice="portale.invito").update(codice="assistenza.invito")


class Migration(migrations.Migration):

    dependencies = [
        ('assistenza', '0003_monte_ore'),
        ('portale', '0001_initial'),
        ('core', '0029_token_ambiti'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(copia, indietro),
        migrations.DeleteModel(
            name='AccessoPortale',
        ),
    ]
