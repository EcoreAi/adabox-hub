"""Pagina Statistiche in due colonne: pagine in tessere, schede delle app come chip, libreria in righe con il tipo."""
import pytest
from django.urls import reverse

from grafici.models import Grafico, Pagina


@pytest.mark.django_db
def test_pagina_statistiche_compatta(client, django_user_model):
    capo = django_user_model.objects.create_superuser("capo", "capo@example.com", "x")
    client.force_login(capo)
    Pagina.objects.create(utente=capo, titolo="Direzione", layout={"widget": [{"id": "g:1"}, {"id": "g:2"}]})
    Pagina.objects.create(utente=capo, titolo="Fatturazione", app="fatturazione", nascosta=True)
    for titolo, tipo, origine in (("Fatturato mensile", "kpi", "chat"), ("Fatturato per mese", "linee", "costruttore"),
                                  ("Previsione fatturato", "previsione", "costruttore"), ("Pipeline per fase", "barre", "vista")):
        Grafico.objects.create(utente=capo, titolo=titolo, tipo=tipo, origine=origine, spec={})
    html = client.get(reverse("grafici:pagine")).content.decode()
    assert 'class="an-statistiche"' in html and html.count('class="an-tessera"') == 1 and "2 grafici" in html
    assert "an-chip" in html and "scheda nascosta" in html and "Mostra" in html          # la scheda nascosta si rimostra
    assert html.count("<tr data-tipo=") == 4
    for famiglia in ('data-tipo="kpi"', 'data-tipo="grafico"', 'data-tipo="previsione"'):
        assert famiglia in html
    assert "Indicatore" in html and ">Ada<" in html and ">Da una lista<" in html and "grafici/statistiche.js" in html


@pytest.mark.django_db
def test_libreria_vuota_e_nessuna_pagina(client, django_user_model):
    u = django_user_model.objects.create_superuser("nuovo", "n@example.com", "x")
    client.force_login(u)
    html = client.get(reverse("grafici:pagine")).content.decode()
    assert "Vuota: crea il primo" in html and "Nessuna pagina libera" in html and "data-strumenti" not in html
