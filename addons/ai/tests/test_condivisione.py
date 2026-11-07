"""Condividere un documento scritto con Ada, un grafico o una tabella della chat con i colleghi: chi riceve legge e
scarica, non modifica; grafici e tabelle si ricalcolano con i permessi di chi guarda; avviso per email e in Discuss."""
from unittest import mock

import pytest
from django.apps import apps
from django.core import mail
from django.urls import reverse

from ai import artifact, documenti_chat
from ai.models import Artifact
from ai.tests.test_chat_gruppo2 import _chat, _utente, s  # noqa: F401  (fixture)


@pytest.fixture
def c(s):
    bruno = _utente("bruno", s["az"])
    bruno.email = "bruno@example.com"
    bruno.save()
    estraneo = _utente("zenobia", s["altra"])                                    # di un'altra azienda
    return {**s, "bruno": bruno, "estraneo": estraneo, "chat": _chat(s)}


def test_documento_condiviso_in_sola_lettura(client, c):
    d = documenti_chat.crea(c["chat"], c["u"], c["az"], "Offerta Rossi", "## Prezzi\n\nLicenza 1.200 €")
    pannello = client.get(f"{reverse('ai:conversazione', args=[c['chat'].pk])}?documento={d.pk}").content.decode()
    assert reverse("ai:condividi", args=["documento", d.pk]) in pannello and "bruno" in pannello and "zenobia" not in pannello
    r = client.post(reverse("ai:condividi", args=["documento", d.pk]), {"persone": [c["bruno"].pk, c["estraneo"].pk]},
                    HTTP_HX_REQUEST="true")
    assert "Condiviso con 1 persona" in r.content.decode() and list(d.condiviso_con.all()) == [c["bruno"]]   # non l'estraneo
    assert mail.outbox[0].to == ["bruno@example.com"] and "Offerta Rossi" in mail.outbox[0].subject
    if apps.is_installed("discuss"):
        from discuss.models import Notifica
        n = Notifica.objects.get(utente=c["bruno"])
        assert n.tipo == "condiviso" and n.url == reverse("ai:documento_condiviso", args=[d.pk])

    client.force_login(c["bruno"])
    pagina = client.get(reverse("ai:documento_condiviso", args=[d.pk])).content.decode()
    assert "Licenza 1.200 €" in pagina and "Condiviso da anna" in pagina and "sola lettura" in pagina
    assert reverse("ai:condividi", args=["documento", d.pk]) not in pagina                  # non lo ricondivide
    assert client.get(reverse("ai:scarica_documento", args=[d.pk, "md"])).content.decode().startswith("# Offerta Rossi")
    preferiti = client.get(reverse("ai:chat")).content.decode().split('data-contenuto="preferite"')[1].split("</section>")[0]
    assert "Condivisi con me" in preferiti and "Offerta Rossi" in preferiti
    assert client.post(reverse("ai:salva_documento", args=[d.pk]), {"testo": "mio", "versione": 1}).status_code == 404
    assert client.post(reverse("ai:condividi", args=["documento", d.pk]), {"persone": []}).status_code == 404

    client.force_login(c["u"])                                                   # tolta la condivisione, non lo vede più
    client.post(reverse("ai:condividi", args=["documento", d.pk]), {})
    client.force_login(c["bruno"])
    assert client.get(reverse("ai:documento_condiviso", args=[d.pk])).status_code == 404
    assert client.get(reverse("ai:scarica_documento", args=[d.pk, "md"])).status_code == 404


def test_grafico_condiviso_con_i_dati_di_chi_guarda(client, c):
    a = Artifact.objects.create(conversazione=c["chat"], utente=c["u"], azienda=c["az"], tipo="tabella", titolo="Aziende",
                                spec={"tipo": "tabella", "vista": "core.aziende", "testo": "", "filtri": {}, "ordina": "",
                                      "campi": [], "limite": 50},
                                dati={"colonne": ["Azienda"], "righe": [["Solo di Anna"]], "link": [""], "totale": 1})
    client.post(reverse("ai:condividi", args=["artifact", a.pk]), {"persone": [c["bruno"].pk]})
    client.force_login(c["bruno"])
    chi = []
    vero = artifact.calcola
    with mock.patch("ai.artifact.calcola", side_effect=lambda spec, ctx: chi.append(ctx.utente) or vero(spec, ctx)):
        pagina = client.get(reverse("ai:artifact", args=[a.pk])).content.decode()
        csv = client.get(reverse("ai:artifact_csv", args=[a.pk])).content.decode()
    assert chi == [c["bruno"], c["bruno"]]                                      # mai con i permessi di Anna
    assert "condiviso da anna" in pagina and "Solo di Anna" not in csv           # e non la sua istantanea
    assert reverse("ai:condividi", args=["artifact", a.pk]) not in pagina
    client.force_login(c["estraneo"])
    assert client.get(reverse("ai:artifact", args=[a.pk])).status_code == 404
