"""«Le mie dashboard»: le pagine che una persona crea (e quelle condivise con lei) non diventano una scheda ciascuna,
che con molte pagine faceva una riga lunghissima; stanno in un menu a tendina subito dopo Dashboard e Statistiche."""
import re

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core.models import Azienda, ProfiloUtente
from grafici import motore
from grafici.models import Pagina

pytestmark = pytest.mark.django_db


def _menu(html):
    """(riga delle schede, pannello di «Le mie dashboard» o None)."""
    riga = html[html.index('<nav class="an-schede"'):html.index("</nav>", html.index('<nav class="an-schede"'))]
    m = re.search(r'<details class="an-menu an-mie">(.*?)</details>', riga, re.S)
    return riga, m.group(1) if m else None


@pytest.fixture
def mie(client, superuser):
    ProfiloUtente.objects.get_or_create(utente=superuser)[0].aziende.add(Azienda.objects.get(pk=1))
    client.force_login(superuser)
    return [motore.nuova_pagina(superuser, f"Pagina {i}") for i in range(9)]


def test_molte_pagine_stanno_nel_menu_dopo_dashboard_e_statistiche(client, mie):
    riga, menu = _menu(client.get(reverse("core:dashboard")).content.decode())
    assert menu is not None
    for p in mie:                                                  # tutte nel menu, nessuna come scheda in riga
        url = reverse("grafici:pagina", args=[p.pk])
        assert f'href="{url}"' in menu and not re.search(r'class="an-scheda[^"]*" href="' + re.escape(url) + '"', riga)
    assert [int(n) for n in re.findall(r'href="/grafici/pagina/(\d+)/"', menu)] == [p.pk for p in mie]      # nel loro ordine
    assert riga.index(">Dashboard<") < riga.index(">Statistiche<") < riga.index(">Le mie dashboard<")
    assert riga.index(">Le mie dashboard<") < riga.index("an-spazio")                                       # a sinistra
    assert "Le tue pagine" not in riga                              # non più in «Altre schede»


def test_la_pagina_aperta_accende_il_menu_e_si_riconosce_nell_elenco(client, mie):
    aperta = mie[4]
    riga, menu = _menu(client.get(reverse("grafici:pagina", args=[aperta.pk])).content.decode())
    assert re.search(r'<details class="an-menu an-mie"><summary class="an-scheda is-attiva">', riga)
    assert re.findall(r'<a href="([^"]+)" title="[^"]*" class="is-attiva" aria-current="page">', menu) == [reverse("grafici:pagina", args=[aperta.pk])]
    riga, _ = _menu(client.get(reverse("core:dashboard")).content.decode())
    assert '<summary class="an-scheda">' in riga                    # sulla Dashboard il menu non è acceso


def test_le_condivise_hanno_la_loro_sezione_con_chi_le_ha_condivise(client, superuser, mie):
    bruno = User.objects.create_user("bruno", "b@example.com", "x", first_name="Bruno", last_name="Neri")
    bruno.user_permissions.add(*Permission.objects.filter(content_type__app_label="grafici"))
    ProfiloUtente.objects.get_or_create(utente=bruno)[0].aziende.add(Azienda.objects.get(pk=1))
    sua = motore.nuova_pagina(bruno, "Vendite di Bruno")
    sua.condivisa = True
    sua.save()
    _, menu = _menu(client.get(reverse("core:dashboard")).content.decode())
    mie_html, condivise = menu.split("Condivise con te")
    assert reverse("grafici:pagina", args=[sua.pk]) in condivise and "Vendite di Bruno<small>di Bruno Neri</small>" in condivise
    assert reverse("grafici:pagina", args=[sua.pk]) not in mie_html and reverse("grafici:pagina", args=[mie[0].pk]) in mie_html


def test_senza_pagine_niente_menu(client, superuser):
    client.force_login(superuser)
    Pagina.objects.filter(utente=superuser, app="").delete()
    riga, menu = _menu(client.get(reverse("core:dashboard")).content.decode())
    assert menu is None and "Le mie dashboard" not in riga and "Nuova pagina" in riga
