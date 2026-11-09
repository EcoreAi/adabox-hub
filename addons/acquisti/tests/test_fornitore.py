"""Pagina del fornitore da link firmato: conferma con data, ritardo, caricamento di un documento, link falso, link
nell'email dell'ordine."""
import datetime

import pytest
from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile

from acquisti import fornitore
from acquisti.tests.test_riscontro import _confermato, scena  # noqa: F401
from core.models import Allegato, Messaggio

OGGI = datetime.date.today()


def test_pagina_del_fornitore(client, scena, settings, tmp_path):  # noqa: F811
    settings.SITO_URL, settings.MEDIA_ROOT = "https://hub.esempio.it", tmp_path
    o = _confermato(*scena)
    url = fornitore.link(o).replace("https://hub.esempio.it", "")
    assert "Conferma l'ordine" in client.get(url).content.decode()
    data = (OGGI + datetime.timedelta(days=10)).isoformat()
    client.post(url, {"azione": "conferma", "nome": "Paolo", "data": data, "riferimento": "OC-77"})
    o.refresh_from_db()
    assert o.consegna_prevista.isoformat() == data and o.riferimento_fornitore == "OC-77"
    client.post(url, {"azione": "ritardo", "data": (OGGI + datetime.timedelta(days=20)).isoformat(), "nota": "camion fermo"})
    o.refresh_from_db()
    assert o.consegna_prevista == OGGI + datetime.timedelta(days=20)
    client.post(url, {"azione": "documento", "tipo": "ddt", "file": SimpleUploadedFile("ddt.pdf", b"%PDF-1")})
    assert Allegato.objects.filter(object_id=o.pk).exists()
    note = list(Messaggio.objects.filter(object_id=o.pk).values_list("corpo", flat=True))
    assert any("camion fermo" in n for n in note) and any("DDT" in n for n in note)
    assert client.get(url[:-4] + "xyz/").status_code == 400


def test_link_nell_email(scena, settings):  # noqa: F811
    from acquisti import lavori
    settings.SITO_URL = "https://hub.esempio.it"
    o = _confermato(*scena)
    lavori.invia(o.pk, User.objects.create_user("buyer").pk)
    assert "/acquisti/fornitore/" in mail.outbox[-1].body
