from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('todo', '0003_proprieta'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='attivita',
            options={'ordering': ['-scadenza', '-creato'], 'permissions': [('vedi_tutte_attivita', 'Può vedere le attività di tutti')],
                     'verbose_name': 'attività', 'verbose_name_plural': 'attività'},
        ),
    ]
