"""Il grafico o la tabella sotto una risposta si ricalcola lì dov'è (↻), con i dati di oggi e l'ora dei dati."""
from django.contrib.auth.models import User

from ai import artifact, strumenti
from ai.models import Artifact, Conversazione
from core.models import Azienda


def _grafico(utente):
    c = strumenti.Contesto(utente=utente, azienda=Azienda.objects.get(pk=1),
                           conversazione=Conversazione.objects.create(utente=utente))
    return Artifact.objects.get(pk=artifact.grafico(c, "core.aziende", per="provincia")["artifact"])


def test_aggiorna_artifact_in_chat(client, superuser):
    Azienda.objects.filter(pk=1).update(provincia="MI")
    a = _grafico(superuser)
    assert a.dati["serie"] == [["MI", 1]]
    Azienda.objects.create(nome="Beta", provincia="RM")
    r = client.post(f"/ai/artifact/{a.pk}/aggiorna/", HTTP_HX_REQUEST="true")
    html = r.content.decode()
    assert r.status_code == 200 and f'id="ai-artifact-{a.pk}"' in html and "RM" in html
    a.refresh_from_db()
    assert ["RM", 1] in a.dati["serie"] and a.aggiornato is not None
    assert "Aggiorna con i dati di oggi" in html and "dati delle" in html


def test_aggiorna_artifact_solo_il_proprietario(client, superuser):
    bruno = User.objects.create_user("bruno", "b@example.com", "x")
    a = Artifact.objects.create(conversazione=Conversazione.objects.create(utente=bruno), utente=bruno, tipo="grafico",
                                titolo="Di Bruno", spec={"tipo": "grafico", "vista": "core.aziende", "per": "provincia"}, dati={})
    assert client.post(f"/ai/artifact/{a.pk}/aggiorna/").status_code == 404
