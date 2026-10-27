import datetime

import pytest
from django.utils import timezone

from core.models import Lavoro
from core.viste.calendario import periodo

pytestmark = [pytest.mark.urls("core.tests.urls_viste"), pytest.mark.django_db]


def _lavoro(funzione, *quando, stato="in_coda"):
    return Lavoro.objects.create(funzione=funzione, stato=stato,
                                 esegui_dopo=timezone.make_aware(datetime.datetime(*quando)))


def _giorni(r):
    return {g["data"]: [e["obj"].funzione for e in g["eventi"]] for s in r.context["settimane"] for g in s}


def test_periodo(rf):
    modo, inizio, fine, rif = periodo(rf.get("/", {"mese": "2026-10"}))
    assert (modo, inizio, fine, rif) == ("mese", datetime.date(2026, 9, 28), datetime.date(2026, 11, 1), datetime.date(2026, 10, 1))
    modo, inizio, fine, _ = periodo(rf.get("/", {"settimana": "2026-10-29"}))
    assert (modo, inizio, fine) == ("settimana", datetime.date(2026, 10, 26), datetime.date(2026, 11, 1))
    assert periodo(rf.get("/", {"mese": "spazzatura"}))[0] == "mese"


def test_mese_con_eventi_nel_giorno_locale(client, superuser):
    _lavoro("a.notte", 2026, 10, 14, 23, 30)            # 23:30 a Roma: resta il 14
    _lavoro("a.fuori", 2026, 12, 1, 9, 0)
    r = client.get("/prova/lavori/calendario/", {"mese": "2026-10"})
    assert r.status_code == 200 and r.context["titolo"] == "Ottobre 2026"
    giorni = _giorni(r)
    assert giorni[datetime.date(2026, 10, 14)] == ["a.notte"] and "a.fuori" not in sum(giorni.values(), [])
    html = r.content.decode()
    assert "<time>23:30</time>" in html and "?mese=2026-09" in html and "?mese=2026-11" in html


def test_settimana_e_filtri(client, superuser):
    _lavoro("a.uno", 2026, 10, 27, 10, 0)
    _lavoro("b.due", 2026, 10, 28, 10, 0, stato="fatto")
    r = client.get("/prova/lavori/calendario/", {"settimana": "2026-10-28", "f_stato": "fatto"})
    assert r.context["modo"] == "settimana" and len(r.context["settimane"]) == 1
    assert sum(_giorni(r).values(), []) == ["b.due"]
    assert "settimana=2026-11-02&amp;f_stato=fatto" in r.content.decode()


def test_troppi_eventi_nel_mese(client, superuser):
    for i in range(6):
        _lavoro(f"a.{i}", 2026, 10, 5, 8 + i, 0)
    g = next(g for s in client.get("/prova/lavori/calendario/", {"mese": "2026-10"}).context["settimane"] for g in s
             if g["data"] == datetime.date(2026, 10, 5))
    assert len(g["eventi"]) == 4 and g["altri"] == 2


def test_nuovo_con_data_precompilata(client, superuser, settings):
    from django.urls import reverse
    # il form di Azienda (vista vera) accetta valori iniziali dalla query string
    html = client.get(reverse("core:aziende_nuovo"), {"nome": "Da calendario", "telefono": "1"}).content.decode()
    assert 'value="Da calendario"' in html
