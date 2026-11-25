"""Le previsioni salvate degli articoli, con chiavi esterne verso Magazzino e Prodotti: il modulo non dipende da loro,
quindi la tabella si crea solo se Magazzino (che dipende da Prodotti) è installato, come il modello in models.py.
Senza Magazzino la migrazione non fa nulla, così il modulo si installa e si collauda anche da solo.

Limite: se Magazzino arriva dopo che questa migrazione è già stata applicata senza di lui, Django la trova applicata
prima delle sue dipendenze e rifiuta di migrare (InconsistentMigrationHistory). Prima di installare Magazzino in
un'istanza che ha già Previsioni: `manage.py migrate previsioni 0003`; dopo l'installazione, `manage.py migrate`."""
import django.db.models.deletion
from django.apps import apps as installate
from django.db import migrations, models

CON_MAGAZZINO = installate.is_installed("magazzino")


class Migration(migrations.Migration):

    dependencies = [
        ('previsioni', '0003_stato_calcolo'),
        *([('magazzino', '0001_initial'), ('prodotti', '0001_initial')] if CON_MAGAZZINO else []),
    ]

    operations = [
        migrations.CreateModel(
            name='PrevisioneArticolo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('per', models.CharField(choices=[('mese', 'mese'), ('settimana', 'settimana')], max_length=10, verbose_name='periodo')),
                ('partenza', models.DecimalField(decimal_places=3, help_text='giacenza + in arrivo − impegnato al momento del calcolo', max_digits=14, verbose_name='giacenza prevista')),
                ('futuro', models.JSONField(default=list, help_text='[[periodo, 10 %, mediana, 90 %]] dal periodo in corso', verbose_name='consumo previsto')),
                ('consumo_mensile', models.DecimalField(decimal_places=3, help_text='media delle mediane, riportata al mese', max_digits=14, verbose_name='consumo previsto al mese')),
                ('esaurimento', models.DateField(blank=True, null=True, verbose_name='esaurimento')),
                ('esaurimento_da', models.DateField(blank=True, help_text='con il consumo alto (90 %)', null=True, verbose_name='esaurimento dal')),
                ('esaurimento_a', models.DateField(blank=True, help_text='con il consumo basso (10 %)', null=True, verbose_name='esaurimento entro')),
                ('riordino', models.DateField(blank=True, null=True, verbose_name='riordino')),
                ('quantita_suggerita', models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True, verbose_name='quantità suggerita')),
                ('stato', models.CharField(choices=[('ok', 'In ordine'), ('riordina_ora', 'Riordina ora'), ('finito', 'Finito'), ('nessun_consumo', 'Nessun consumo previsto'), ('oltre', "Oltre l'orizzonte")], max_length=20, verbose_name='stato')),
                ('affidabilita', models.JSONField(default=dict, verbose_name='affidabilità')),
                ('modello', models.CharField(blank=True, max_length=120, verbose_name='modello')),
                ('calcolata_il', models.DateTimeField(verbose_name='calcolata il')),
                ('azienda', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.azienda', verbose_name='azienda')),
                ('magazzino', models.ForeignKey(blank=True, help_text="vuoto: sul totale dei magazzini dell'azienda", null=True, on_delete=django.db.models.deletion.CASCADE, related_name='previsioni_articolo', to='magazzino.magazzino', verbose_name='magazzino')),
                ('prodotto', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='previsioni_articolo', to='prodotti.prodotto', verbose_name='prodotto')),
            ],
            options={
                'verbose_name': 'previsione di un articolo',
                'verbose_name_plural': 'previsioni degli articoli',
                'abstract': False,
                'indexes': [models.Index(fields=['azienda'], name='previsioni__azienda_fdb33f_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('magazzino__isnull', False)), fields=('azienda', 'prodotto', 'magazzino'), name='previsioni_articolo_magazzino'), models.UniqueConstraint(condition=models.Q(('magazzino__isnull', True)), fields=('azienda', 'prodotto'), name='previsioni_articolo_totale')],
            },
        ),
    ] if CON_MAGAZZINO else []
