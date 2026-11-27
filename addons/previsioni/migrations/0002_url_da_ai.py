"""L'URL del servizio di previsione passa dall'assistente (`ai.url_forecast`) al modulo (`previsioni.url_servizio`):
se l'assistente ne aveva uno globale e il modulo no, si copia. Una volta sola: quello del modulo, se c'è, non si tocca.
All'indietro non fa niente (l'impostazione dell'assistente resta dov'era)."""
from django.db import migrations


def copia_url(apps, schema_editor):
    Parametro = apps.get_model("core", "Parametro")
    vecchio = Parametro.objects.filter(chiave="ai.url_forecast", azienda__isnull=True).first()
    url = vecchio.valore.strip() if vecchio and isinstance(vecchio.valore, str) else ""
    if not url:
        return
    nuovo = Parametro.objects.filter(chiave="previsioni.url_servizio", azienda__isnull=True).first()
    if nuovo is None:
        Parametro.objects.create(chiave="previsioni.url_servizio", valore=url, azienda=None)
    elif not (isinstance(nuovo.valore, str) and nuovo.valore.strip()):
        nuovo.valore = url
        nuovo.save(update_fields=["valore"])


class Migration(migrations.Migration):

    dependencies = [
        ("previsioni", "0001_iniziale"),
        ("core", "0006_parametri"),
    ]

    operations = [
        migrations.RunPython(copia_url, migrations.RunPython.noop),
    ]
