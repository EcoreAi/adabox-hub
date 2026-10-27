import threading
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from core import lavori
from core.models import Azienda, Lavoro

P = "core.tests.lavori_prova."


@pytest.fixture
def asincrono(settings):
    settings.LAVORI_SINCRONI = False


@pytest.mark.django_db
def test_sincrono():
    lavoro = lavori.accoda(P + "somma", a=1, b=2)
    assert (lavoro.stato, lavoro.risultato, lavoro.tentativi) == (Lavoro.FATTO, "3", 1)


@pytest.mark.django_db
def test_sincrono_fallito_non_risale():
    lavoro = lavori.accoda(P + "esplode")
    assert lavoro.stato == Lavoro.FALLITO and "boom" in lavoro.errore


@pytest.mark.django_db
def test_scritture_annullate_se_fallisce():
    lavori.accoda(P + "crea_e_esplode", nome="Fantasma")
    assert not Azienda.objects.filter(nome="Fantasma").exists()


@pytest.mark.django_db
def test_funzione_inesistente():
    assert lavori.accoda("core.tests.lavori_prova.nessuna").stato == Lavoro.FALLITO
    assert lavori.accoda("modulo_che_non_esiste.f").stato == Lavoro.FALLITO


@pytest.mark.django_db
def test_argomenti_non_serializzabili():
    with pytest.raises(TypeError):
        lavori.accoda(P + "somma", a=object(), b=1)


@pytest.mark.django_db
def test_coda_e_worker(asincrono):
    lavoro = lavori.accoda(P + "somma", a=2, b=3)
    assert lavoro.stato == Lavoro.IN_CODA
    assert lavori.esegui_uno() == lavoro
    lavoro.refresh_from_db()
    assert lavoro.stato == Lavoro.FATTO and lavoro.risultato == "5"
    assert lavori.esegui_uno() is None


@pytest.mark.django_db
def test_ritardo(asincrono):
    lavoro = lavori.accoda(P + "somma", a=1, b=1, ritardo=3600)
    assert lavori.esegui_uno() is None
    Lavoro.objects.filter(pk=lavoro.pk).update(esegui_dopo=timezone.now())
    assert lavori.esegui_uno() == lavoro


@pytest.mark.django_db
def test_ritentativi_con_backoff(asincrono):
    lavoro = lavori.accoda(P + "esplode", max_tentativi=3)
    for tentativo, attesa in [(1, 60), (2, 300)]:
        prima = timezone.now()
        lavori.esegui_uno()
        lavoro.refresh_from_db()
        assert lavoro.stato == Lavoro.IN_CODA and lavoro.tentativi == tentativo
        assert lavoro.esegui_dopo >= prima + timedelta(seconds=attesa - 1)
        Lavoro.objects.filter(pk=lavoro.pk).update(esegui_dopo=timezone.now())
    lavori.esegui_uno()
    lavoro.refresh_from_db()
    assert lavoro.stato == Lavoro.FALLITO and lavoro.tentativi == 3 and "boom" in lavoro.errore


@pytest.mark.django_db
def test_riprova_e_sblocca(asincrono):
    lavoro = lavori.accoda(P + "somma", a=1, b=1)
    Lavoro.objects.filter(pk=lavoro.pk).update(stato=Lavoro.IN_CORSO, iniziato=timezone.now() - timedelta(hours=2))
    assert lavori.sblocca() == 1
    lavoro.refresh_from_db()
    assert lavoro.stato == Lavoro.IN_CODA
    lavoro.stato = Lavoro.FALLITO
    lavoro.save()
    lavori.riprova(lavoro)
    lavoro.refresh_from_db()
    assert lavoro.stato == Lavoro.IN_CODA and lavoro.tentativi == 0


@pytest.mark.django_db
def test_comando_una_volta(asincrono, capsys):
    for i in range(3):
        lavori.accoda(P + "somma", a=i, b=0)
    call_command("worker", "--una-volta")
    assert Lavoro.objects.filter(stato=Lavoro.FATTO).count() == 3
    assert capsys.readouterr().out.count(": fatto") == 3


@pytest.mark.django_db
def test_pagina_lavori(client, staff, superuser):
    lavoro = lavori.accoda(P + "esplode")
    assert client.get("/core/lavoro/").status_code == 200
    html = client.get(f"/core/lavoro/{lavoro.pk}/").content.decode()
    assert "boom" in html and "Riprova" in html
    client.post(f"/core/lavoro/{lavoro.pk}/bottone/riprova/")
    lavoro.refresh_from_db()
    assert lavoro.stato == Lavoro.IN_CODA
    assert client.get("/core/lavoro/nuovo/").status_code == 403
    client.force_login(staff)
    assert client.get("/core/lavoro/").status_code == 403


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
def test_due_worker_non_prendono_lo_stesso_lavoro(settings):
    from core.tests import lavori_prova
    settings.LAVORI_SINCRONI = False
    lavori_prova.ESEGUITI.clear()
    for i in range(20):
        lavori.accoda(P + "lento", n=i)

    def worker():
        try:
            while lavori.esegui_uno() is not None:
                pass
        finally:
            connection.close()
    fili = [threading.Thread(target=worker) for _ in range(3)]
    for f in fili:
        f.start()
    for f in fili:
        f.join()
    assert sorted(lavori_prova.ESEGUITI) == list(range(20))
    assert set(Lavoro.objects.values_list("tentativi", flat=True)) == {1}


@pytest.mark.django_db
def test_sigterm_ferma_il_worker(asincrono, capsys):
    import os
    import signal
    precedenti = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    timer = threading.Timer(0.3, os.kill, args=(os.getpid(), signal.SIGTERM))
    timer.start()
    try:
        call_command("worker", "--pausa", "0.1")
    finally:
        timer.cancel()
        signal.signal(signal.SIGTERM, precedenti[0])
        signal.signal(signal.SIGINT, precedenti[1])
    out = capsys.readouterr().out
    assert "worker avviato" in out and "worker fermato" in out
