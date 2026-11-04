import json
import re

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import Azienda
from grafici import motore
from grafici.tests.aiuti import in_pagina
from grafici.models import Grafico, Pagina


@pytest.fixture
def attivita(db):
    from todo.models import Attivita
    az = Azienda.objects.get(pk=1)
    oggi = timezone.localdate()
    Attivita.objects.create(azienda=az, titolo="Alfa", scadenza=oggi)
    Attivita.objects.create(azienda=az, titolo="Beta", scadenza=oggi, stato=Attivita.FATTA)
    Attivita.objects.create(azienda=az, titolo="Gamma", stato=Attivita.FATTA)
    return az


def _serie(html, dom):
    m = re.search(rf'<script id="{dom}" type="application/json">(.*?)</script>', html)
    return json.loads(m.group(1)) if m else None


@pytest.mark.django_db
def test_obiettivo_sul_grafico_e_sul_kpi_e_png(client, superuser, attivita):
    r = client.post(reverse("grafici:costruttore"), {"vista": "todo.attivita", "per": "stato", "misura": "count", "tipo": "barre",
                                                     "massimo": "30", "obiettivo": "5", "destinazione": "nuova", "titolo_nuova": "Obiettivi"})
    g = Grafico.objects.get(utente=superuser)
    obiettivi = Pagina.objects.get(titolo="Obiettivi")
    assert r.status_code == 302 and g.opzioni == {"obiettivo": 5.0}
    html = client.get(reverse("grafici:pagina", args=[obiettivi.pk])).content.decode()
    assert _serie(html, f"wd-g-{g.pk}")["obiettivo"] == 5.0 and f'data-an-png="wd-g-{g.pk}"' in html
    # modifica: il form ripresenta l'obiettivo; svuotato, sparisce
    html = client.get(reverse("grafici:grafico_costruttore", args=[g.pk])).content.decode()
    assert 'name="obiettivo" value="5.0"' in html
    client.post(reverse("grafici:grafico_costruttore", args=[g.pk]), {"vista": "todo.attivita", "per": "stato", "misura": "count", "tipo": "barre",
                                                                      "massimo": "30", "obiettivo": ""})
    g.refresh_from_db()
    assert g.opzioni == {}
    # KPI con obiettivo: barra di avanzamento e percentuale
    k = in_pagina(obiettivi, utente=superuser, titolo="Scadenze", tipo="kpi", opzioni={"obiettivo": 4},
                               spec={"vista": "todo.attivita", "misura": "count", "data": "scadenza", "periodo": "mese"})
    html = client.get(reverse("grafici:pagina", args=[obiettivi.pk])).content.decode()
    serie = _serie(html, f"wd-g-{k.pk}")
    assert serie["percento"] == 50 and serie["obiettivo_testo"] == "4" and "50 % dell'obiettivo 4" in html and 'aria-valuenow="50"' in html
    # anteprima del costruttore con obiettivo scritto all'italiana
    html = client.get(reverse("grafici:costruttore") + "?vista=todo.attivita&tipo=kpi&data=scadenza&periodo=mese&obiettivo=1.000,5").content.decode()
    assert "dell'obiettivo 1.000,50" in html


@pytest.mark.django_db
def test_la_riga_delle_schede_resta_corta_e_il_resto_sta_nel_menu_per_area(client, superuser, attivita, monkeypatch):
    html = client.get(reverse("core:dashboard")).content.decode()
    assert not re.search(r'class="an-scheda an-scheda-app', html) and "Altre schede" in html and "an-altre-titolo" in html
    assert reverse("grafici:pagina_app", args=["todo"]) in html and "Vendite e clienti" in html
    assert '<details class="an-menu an-nuova">' in html and "an-nuova-campo" not in html
    # la scheda aperta è in vista, anche se di norma sta nel menu
    url = reverse("grafici:pagina_app", args=["todo"])
    html = client.get(url).content.decode()
    assert re.search(r'class="an-scheda an-scheda-app is-attiva"[^>]*href="' + url + '"', html)
    # un'app personalizzata resta in vista, fino al limite
    p = Pagina.objects.get(utente=superuser, app="todo")
    in_pagina(p, utente=superuser, titolo="X", spec={"vista": "todo.attivita", "per": "stato"})
    html = client.get(reverse("core:dashboard")).content.decode()
    assert re.search(r'class="an-scheda an-scheda-app"[^>]*href="' + url + '"', html)
    monkeypatch.setattr(motore, "MAX_SCHEDE_APP", 0)
    assert not re.search(r'class="an-scheda an-scheda-app"', client.get(reverse("core:dashboard")).content.decode())
    # le pagine oltre il limite vanno nel menu, e quella aperta resta in vista
    monkeypatch.setattr(motore, "MAX_SCHEDE_PAGINE", 2)
    pagine = [Pagina.objects.create(utente=superuser, titolo=f"Pagina {i}", ordine=i) for i in range(4)]
    r = client.get(reverse("grafici:pagina", args=[pagine[3].pk]))
    html = r.content.decode()
    assert "Le tue pagine" in html and re.search(r'class="an-scheda is-attiva"[^>]*href="' + reverse("grafici:pagina", args=[pagine[3].pk]) + '"', html)
