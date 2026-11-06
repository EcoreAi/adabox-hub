"""Progetti collegati a record del gestionale: si collega solo ciò che l'utente vede, Ada lo riceve come contesto, dal
record si torna al progetto. Il collegamento non dà accesso a nulla in più."""
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ai import collegamenti, contesto_utente
from ai.models import CollegamentoProgetto, Conversazione, ProgettoChat
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)
from contatti.models import Contatto

import pytest


@pytest.fixture
def c(s, client):
    s["u"].user_permissions.add(*Permission.objects.filter(content_type__app_label="contatti"))
    u = User.objects.get(pk=s["u"].pk)
    client.force_login(u)
    rossi = Contatto.objects.create(azienda=s["az"], nome="Officine Rossi Srl")
    altrove = Contatto.objects.create(azienda=s["altra"], nome="Officine Rossi Bis")
    progetto = ProgettoChat.objects.create(utente=u, azienda=s["az"], nome="Offerta Rossi")
    return {**s, "u": u, "rossi": rossi, "altrove": altrove, "progetto": progetto, "ct": ContentType.objects.get_for_model(Contatto).pk}


def test_cerca_e_collega(client, c):
    html = client.get(reverse("ai:cerca_collegamento", args=[c["progetto"].pk]), {"q": "Officine Rossi"}).content.decode()
    assert "Officine Rossi Srl" in html and "Officine Rossi Bis" not in html                     # solo dell'azienda corrente
    assert "Modifica" not in html                                                                 # niente registro modifiche
    client.post(reverse("ai:collega", args=[c["progetto"].pk]), {"ct": c["ct"], "record": c["rossi"].pk})
    assert CollegamentoProgetto.objects.filter(progetto=c["progetto"], object_id=c["rossi"].pk).count() == 1
    client.post(reverse("ai:collega", args=[c["progetto"].pk]), {"ct": c["ct"], "record": c["rossi"].pk})       # niente doppioni
    client.post(reverse("ai:collega", args=[c["progetto"].pk]), {"ct": c["ct"], "record": c["altrove"].pk})     # non visibile
    assert CollegamentoProgetto.objects.count() == 1
    pagina = client.get(reverse("ai:progetto", args=[c["progetto"].pk])).content.decode()
    assert "Officine Rossi Srl" in pagina and "ai-chip-collegamento" in pagina
    coll = CollegamentoProgetto.objects.get()
    client.post(reverse("ai:scollega", args=[c["progetto"].pk, coll.pk]))
    assert not CollegamentoProgetto.objects.exists()


def test_ada_riceve_i_record_collegati(c):
    CollegamentoProgetto.objects.create(progetto=c["progetto"], content_type_id=c["ct"], object_id=c["rossi"].pk)
    CollegamentoProgetto.objects.create(progetto=c["progetto"], content_type_id=c["ct"], object_id=c["altrove"].pk)  # non visibile
    chat = Conversazione.objects.create(utente=c["u"], titolo="x", progetto=c["progetto"])
    nota = contesto_utente.nota_progetto(chat)
    assert "Officine Rossi Srl" in nota and f"vista contatti.contatti, id {c['rossi'].pk}" in nota and "leggi_record" in nota
    assert "Bis" not in nota


def test_dal_record_al_progetto(client, c):
    url_record = reverse("contatti:contatti_dettaglio", args=[c["rossi"].pk])
    pagina = client.get(url_record).content.decode()
    assert "Aree di lavoro collegate" in pagina and "Collega a quest'area di lavoro" in pagina
    r = client.post(reverse("ai:collega", args=[c["progetto"].pk]), {"ct": c["ct"], "record": c["rossi"].pk, "indietro": url_record})
    assert r.url == url_record
    pagina = client.get(url_record).content.decode()
    assert reverse("ai:progetto", args=[c["progetto"].pk]) in pagina.split("Aree di lavoro collegate")[1]
    assert client.post(reverse("ai:collega", args=[c["progetto"].pk]), {"ct": c["ct"], "record": 1, "indietro": "//esterno.it/"}).url.startswith("/ai/")


def test_progetto_di_un_altro(client, c):
    altro = User.objects.create_user("bruno", password="x")
    altro.user_permissions.set(Permission.objects.filter(content_type__app_label__in=["ai", "contatti"]))
    client.force_login(altro)
    assert client.post(reverse("ai:collega", args=[c["progetto"].pk]), {"ct": c["ct"], "record": c["rossi"].pk}).status_code == 404
    assert collegamenti.progetti_del_record(altro, c["az"], c["rossi"]) == []
