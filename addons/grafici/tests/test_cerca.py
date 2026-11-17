"""I grafici salvati e le pagine di Analisi nella ricerca generale, con la visibilità di ciascuno."""
from django.contrib.auth.models import User
from django.urls import reverse

from grafici.models import Grafico, Pagina


def _grafico(utente, titolo):
    return Grafico.objects.create(utente=utente, titolo=titolo, tipo="barre",
                                  spec={"misura_aziendale": "fatturazione.fatturato", "per": "mese", "periodo": "anno"})


def test_trova_il_grafico_delle_vendite(client, superuser):
    g = _grafico(superuser, "Fatturato per mese")
    html = client.get("/cerca/", {"q": "grafico vendite quest'anno"}).content.decode()
    assert "Fatturato per mese" in html and reverse("grafici:grafico", args=[g.pk]) in html
    assert "?chiedi=" not in html                                               # il grafico c'è: niente rimando ad Ada


def test_trova_le_pagine(client, superuser):
    Pagina.objects.create(utente=superuser, titolo="Direzione vendite")
    assert "Direzione vendite" in client.get("/cerca/", {"q": "vendite"}).content.decode()


def test_non_trova_i_grafici_degli_altri(client, db):
    """Chi non è superutente trova solo i suoi grafici (e quelli condivisi con lui), non quelli dei colleghi."""
    from django.contrib.auth.models import Permission
    anna = User.objects.create_user("anna", "a@example.com", "x")
    anna.user_permissions.add(*Permission.objects.filter(content_type__app_label="grafici", codename__startswith="view_"))
    client.force_login(anna)
    _grafico(anna, "Fatturato di Anna")
    _grafico(User.objects.create_user("bruno", "b@example.com", "x"), "Fatturato segreto")
    html = client.get("/cerca/", {"q": "fatturato"}).content.decode()
    assert "Fatturato di Anna" in html and "Fatturato segreto" not in html
