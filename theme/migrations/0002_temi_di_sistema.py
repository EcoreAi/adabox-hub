from django.db import migrations

TEMI = [
    {"nome": "Adabox Classico", "descrizione": "L'aspetto di sempre: header chiaro e blu.", "foglio": "", "colore_barra": "", "attivo": True},
    {"nome": "Adabox Green", "descrizione": "Header blu notte, verde acqua per le voci scelte, fondi caldi.",
     "foglio": "theme/temi/adabox-green.css", "colore_barra": "#22394a", "attivo": False},
]


def crea(apps, schema_editor):
    Tema = apps.get_model("theme", "Tema")
    for dati in TEMI:
        Tema.objects.update_or_create(nome=dati["nome"], defaults={**dati, "di_sistema": True})


def togli(apps, schema_editor):
    apps.get_model("theme", "Tema").objects.filter(di_sistema=True, nome__in=[t["nome"] for t in TEMI]).delete()


class Migration(migrations.Migration):
    dependencies = [("theme", "0001_temi")]
    operations = [migrations.RunPython(crea, togli)]
