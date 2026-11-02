from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0017_utente_esterno'),
    ]

    operations = [
        migrations.CreateModel(
            name='DueFattori',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('segreto_cifrato', models.TextField(editable=False, verbose_name='segreto cifrato')),
                ('attiva_dal', models.DateTimeField(blank=True, editable=False, help_text='vuoto finché la procedura di attivazione non è conclusa', null=True, verbose_name='attiva dal')),
                ('codici_recupero', models.JSONField(default=list, editable=False, verbose_name='codici di recupero')),
                ('ultimo_passo', models.BigIntegerField(default=0, editable=False, help_text='un codice già usato non vale una seconda volta', verbose_name='ultimo passo usato')),
                ('fallimenti', models.PositiveSmallIntegerField(default=0, editable=False, verbose_name='tentativi falliti')),
                ('bloccata_fino', models.DateTimeField(blank=True, editable=False, null=True, verbose_name='bloccata fino a')),
                ('generazione', models.PositiveIntegerField(default=1, editable=False, verbose_name='generazione dei dispositivi fidati')),
                ('utente', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='due_fattori', to=settings.AUTH_USER_MODEL, verbose_name='utente')),
            ],
            options={'verbose_name': 'autenticazione a due fattori', 'verbose_name_plural': 'autenticazioni a due fattori'},
        ),
    ]
