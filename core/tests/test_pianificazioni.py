import threading
from datetime import datetime, timedelta

import pytest
from django.db import connection
from django.utils import timezone

from core import lavori
from core.management.commands import modulo_applica as applica
from core.models import Lavoro, Modulo, Pianificazione
from core.registry import manifest

P = "core.tests.lavori_prova."


def _locale(*args):
    return timezone.make_aware(datetime(*args))


def test_intervallo():
    assert lavori.intervallo("15m") == timedelta(minutes=15)
    assert lavori.intervallo("2h") == timedelta(hours=2)
    assert lavori.intervallo("1d") == timedelta(days=1)


def test_prossima_senza_alle():
    da = _locale(2026, 10, 27, 10, 0)
    assert lavori.prossima("15m", da=da) == da + timedelta(minutes=15)


def test_prossima_con_alle():
    assert lavori.prossima("1d", "07:00", _locale(2026, 10, 27, 6, 0)) == _locale(2026, 10, 27, 7, 0)
    assert lavori.prossima("1d", "07:00", _locale(2026, 10, 27, 7, 0)) == _locale(2026, 10, 28, 7, 0)
    assert lavori.prossima("1d", "07:00", _locale(2026, 10, 27, 10, 0)) == _locale(2026, 10, 28, 7, 0)
    assert lavori.prossima("2d", "07:00", _locale(2026, 10, 27, 7, 0)) == _locale(2026, 10, 29, 7, 0)


def test_prossima_attraverso_il_cambio_d_ora():
    # 25 ottobre 2026: fine dell'ora legale a Roma; le 07:00 restano le 07:00 locali
    p = lavori.prossima("1d", "07:00", _locale(2026, 10, 24, 8, 0))
    assert timezone.localtime(p).hour == 7 and timezone.localtime(p).day == 25


@pytest.mark.django_db
def test_sincronizza_dal_manifest():
    voci = [{"nome": "A", "funzione": P + "somma", "ogni": "1h"}, {"nome": "B", "funzione": P + "somma", "ogni": "1d", "alle": "02:30"}]
    lavori.sincronizza_pianificazioni("alfa", voci)
    assert set(Pianificazione.objects.filter(modulo="alfa").values_list("nome", flat=True)) == {"A", "B"}
    b = Pianificazione.objects.get(modulo="alfa", nome="B")
    assert timezone.localtime(b.prossima_esecuzione).strftime("%H:%M") == "02:30"
    b.attiva = False
    b.save()
    lavori.sincronizza_pianificazioni("alfa", voci[1:])
    assert list(Pianificazione.objects.filter(modulo="alfa").values_list("nome", "attiva")) == [("B", False)]


@pytest.mark.django_db
def test_pianifica_scadute(settings):
    settings.LAVORI_SINCRONI = False
    lavori.sincronizza_pianificazioni("alfa", [{"nome": "A", "funzione": P + "somma", "ogni": "1h"}])
    p = Pianificazione.objects.get(nome="A")
    assert lavori.pianifica_scadute() == []
    Pianificazione.objects.filter(pk=p.pk).update(prossima_esecuzione=timezone.now() - timedelta(minutes=1))
    assert [x.pk for x in lavori.pianifica_scadute()] == [p.pk]
    p.refresh_from_db()
    assert p.prossima_esecuzione > timezone.now() + timedelta(minutes=59) and p.ultima_esecuzione
    assert Lavoro.objects.filter(funzione=P + "somma", stato=Lavoro.IN_CODA).count() == 1
    # scaduta di nuovo ma il lavoro precedente è ancora in coda: non se ne accoda un altro
    Pianificazione.objects.filter(pk=p.pk).update(prossima_esecuzione=timezone.now() - timedelta(minutes=1))
    assert lavori.pianifica_scadute() == []
    assert Lavoro.objects.filter(funzione=P + "somma").count() == 1


@pytest.mark.django_db
def test_disattivata_non_parte():
    lavori.sincronizza_pianificazioni("alfa", [{"nome": "A", "funzione": P + "somma", "ogni": "1h"}])
    Pianificazione.objects.update(attiva=False, prossima_esecuzione=timezone.now() - timedelta(hours=1))
    assert lavori.pianifica_scadute() == []


@pytest.mark.django_db
def test_modulo_applica_crea_e_toglie(addons_tmp):
    cartella = addons_tmp.crea("alfa", cron=[{"nome": "Ogni ora", "funzione": P + "somma", "ogni": "1h"}])
    m = manifest.leggi(cartella)
    lavori.sincronizza_pianificazioni(m.slug, m.cron)            # come fa _installa
    assert Pianificazione.objects.filter(modulo="alfa").count() == 1
    Modulo.objects.create(slug="alfa", nome="Alfa", stato=Modulo.INSTALLATO)
    applica.Command()._disinstalla("alfa", elimina_dati=False)
    assert not Pianificazione.objects.filter(modulo="alfa").exists()


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_due_worker_accodano_una_volta(settings):
    settings.LAVORI_SINCRONI = False
    lavori.sincronizza_pianificazioni("alfa", [{"nome": "A", "funzione": P + "lento", "ogni": "1h"}])
    Pianificazione.objects.update(prossima_esecuzione=timezone.now() - timedelta(minutes=1))
    barriera = threading.Barrier(4)

    def worker():
        try:
            barriera.wait()
            lavori.pianifica_scadute()
        finally:
            connection.close()
    fili = [threading.Thread(target=worker) for _ in range(4)]
    for f in fili:
        f.start()
    for f in fili:
        f.join()
    assert Lavoro.objects.filter(funzione=P + "lento").count() == 1
