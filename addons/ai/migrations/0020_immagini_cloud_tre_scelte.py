"""«Immagini verso i modelli cloud» passa da sì/no a tre scelte: chi l'aveva accesa resta su «Sempre», gli altri
passano a «Con la conferma dell'utente» (decisione del 2026-11-06)."""
from django.db import migrations


def avanti(apps, schema_editor):
    Parametro = apps.get_model("core", "Parametro")
    for p in Parametro.objects.filter(chiave="ai.immagini_cloud"):
        if p.valore in (True, "True", "true", 1):
            p.valore = "sempre"
        elif p.valore not in ("mai", "conferma", "sempre"):
            p.valore = "conferma"
        p.save(update_fields=["valore"])


def indietro(apps, schema_editor):
    Parametro = apps.get_model("core", "Parametro")
    for p in Parametro.objects.filter(chiave="ai.immagini_cloud"):
        p.valore = p.valore == "sempre"
        p.save(update_fields=["valore"])


class Migration(migrations.Migration):
    dependencies = [("ai", "0019_turno_web"), ("core", "0029_token_ambiti")]
    operations = [migrations.RunPython(avanti, indietro)]
