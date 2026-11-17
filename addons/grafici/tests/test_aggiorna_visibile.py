"""Ogni grafico salvato ha il ricalcolo a portata di mano (↻ accanto al titolo, con l'ora dei dati), non solo nel menu ⋯."""
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from grafici import motore
from grafici.models import Grafico


def test_icona_aggiorna_sul_widget(superuser):
    g = Grafico.objects.create(utente=superuser, titolo="Aziende per provincia", tipo="barre",
                               spec={"vista": "core.aziende", "per": "provincia"})
    req = RequestFactory().get("/")
    req.user, req.azienda = superuser, None
    w = motore.widget_salvato(g, req)
    card = render_to_string("grafici/_widget.html", {"w": w, "mio": True}, request=req)
    testa = card.split('<details class="an-menu">')[0]                          # prima del menu ⋯
    url = reverse("grafici:grafico_aggiorna", args=[g.pk])
    assert f'hx-post="{url}"' in testa and "an-aggiorna" in testa and "dati delle" in testa
