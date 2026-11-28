import ai.models
from django.db import migrations, models


class Migration(migrations.Migration):
    """L'URL dell'API di un provider accetta i nomi dei container (http://ollama:11434/v1): la colonna resta com'è."""

    dependencies = [
        ('ai', '0043_costi_della_voce'),
    ]

    operations = [
        migrations.AlterField(
            model_name='provider',
            name='base_url',
            field=models.CharField(blank=True, help_text='vuoto = quello predefinito del tipo', max_length=200, validators=[ai.models.valida_url_api], verbose_name="URL dell'API"),
        ),
    ]
