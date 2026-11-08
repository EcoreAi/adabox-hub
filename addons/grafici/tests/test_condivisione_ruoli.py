"""RPT-01: una pagina di Analisi si condivide con tutta l'azienda o con alcuni ruoli e gruppi; la dashboard ha una
disposizione di partenza per ruolo, impostata dall'amministratore."""
import pytest
from django.contrib.auth.models import Group, Permission, User
from django.urls import reverse

from core.models import Azienda, DashboardUtente, ProfiloUtente, Ruolo
from grafici import motore
from grafici.models import Pagina


def _collega(nome, ruolo=None, gruppo=None):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(content_type__app_label="grafici"))
    profilo, _ = ProfiloUtente.objects.get_or_create(utente=u)
    profilo.aziende.add(Azienda.objects.get(pk=1))
    if ruolo:
        profilo.ruolo = ruolo
        profilo.save()
    if gruppo:
        u.groups.add(gruppo)
    return User.objects.get(pk=u.pk)


@pytest.fixture
def scena(db, superuser):
    ProfiloUtente.objects.get_or_create(utente=superuser)[0].aziende.add(Azienda.objects.get(pk=1))
    comm, amm = Ruolo.objects.create(nome="Commerciale"), Ruolo.objects.create(nome="Amministrazione")
    squadra = Group.objects.create(name="Squadra Nord")
    return {"comm": comm, "amm": amm, "squadra": squadra,
            "pagina": motore.nuova_pagina(superuser, "Vendite del mese"),
            "carla": _collega("carla", ruolo=comm), "aldo": _collega("aldo", ruolo=amm),
            "nico": _collega("nico", gruppo=squadra)}


def _vede(client, utente, pagina):
    client.force_login(utente)
    return client.get(reverse("grafici:pagina", args=[pagina.pk])).status_code == 200


def test_condivisa_con_un_ruolo_e_un_gruppo(client, superuser, scena):
    p = scena["pagina"]
    html = client.get(reverse("grafici:pagina", args=[p.pk])).content.decode()
    assert 'value="scelti"' in html and "Commerciale" in html and "Squadra Nord" in html
    client.post(reverse("grafici:condividi", args=[p.pk]), {"a": "scelti", "ruoli": [scena["comm"].pk], "gruppi": [scena["squadra"].pk]})
    p.refresh_from_db()
    assert not p.condivisa and motore.a_chi(p) == "ruolo Commerciale, gruppo Squadra Nord"
    assert _vede(client, scena["carla"], p) and _vede(client, scena["nico"], p) and not _vede(client, scena["aldo"], p)
    client.force_login(scena["nico"])
    tab = client.get(reverse("grafici:pagine")).content.decode()          # nico la trova tra le condivise
    assert "Vendite del mese" in tab

    client.force_login(superuser)
    client.post(reverse("grafici:condividi", args=[p.pk]), {"a": "azienda", "ruoli": [scena["comm"].pk]})
    p.refresh_from_db()
    assert p.condivisa and not p.ruoli.exists() and _vede(client, scena["aldo"], p)
    client.force_login(superuser)
    client.post(reverse("grafici:condividi", args=[p.pk]), {"a": "nessuno"})
    assert not _vede(client, scena["carla"], Pagina.objects.get(pk=p.pk))


def test_dashboard_di_partenza_per_ruolo(client, superuser, scena):
    from core import dashboard as dash
    disposizione = {"widget": [{"id": "x:kpi", "w": 4}], "nascosti": []}
    DashboardUtente.objects.create(utente=superuser, layout=disposizione)
    r = client.post(reverse("core:dashboard_per_ruolo"), {"ruolo": scena["comm"].pk})
    assert r.status_code == 302 and Ruolo.objects.get(pk=scena["comm"].pk).dashboard == disposizione
    assert dash.layout_di(scena["carla"]) == disposizione and dash.layout_di(scena["aldo"]) == {}
    assert not dash.personalizzata(scena["carla"])
    DashboardUtente.objects.create(utente=scena["carla"], layout={"widget": [], "nascosti": ["x:kpi"]})
    assert dash.layout_di(scena["carla"])["nascosti"] == ["x:kpi"]               # la sua vince
    client.post(reverse("core:dashboard_per_ruolo"), {"ruolo": scena["comm"].pk, "azione": "togli"})
    assert Ruolo.objects.get(pk=scena["comm"].pk).dashboard == {}
    client.force_login(scena["aldo"])                                           # senza il permesso sui ruoli no
    assert client.post(reverse("core:dashboard_per_ruolo"), {"ruolo": scena["comm"].pk}).status_code == 403
    assert "dashboard_per_ruolo" not in client.get(reverse("core:dashboard")).content.decode()
