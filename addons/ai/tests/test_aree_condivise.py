"""Aree di lavoro condivise: istruzioni, file, cartella e record in comune; chat private salvo quelle condivise (in sola
lettura); le impostazioni le cambia solo chi ha creato l'area; chi esce perde l'accesso e le sue chat escono dall'area."""
from datetime import time as ora

from django.contrib.auth.models import Permission, User
from django.urls import reverse

from ai import aree, contesto_utente
from ai.models import Conversazione, MembroArea, Pianificata, ProgettoChat
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)
from core.models import Azienda

import pytest


def _utente(nome, azienda):
    u = User.objects.create_user(nome, password="x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def a(s, client):
    bruno = _utente("bruno", s["az"])
    fuori = _utente("carla", Azienda.objects.create(nome="Terza"))
    area = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Offerta Rossi", istruzioni="Tono formale.")
    return {**s, "bruno": bruno, "fuori": fuori, "area": area}


def test_condividere_dal_form(client, a):
    pagina = client.get(reverse("ai:progetti_modifica", args=[a["area"].pk])).content.decode()
    assert "Bruno" in pagina and "Carla" not in pagina                                   # solo colleghi della stessa azienda
    client.post(reverse("ai:progetti_modifica", args=[a["area"].pk]), {"nome": "Offerta Rossi", "istruzioni": "Tono formale.", "membri": [a["bruno"].pk]})
    assert list(a["area"].membri.values_list("utente_id", flat=True)) == [a["bruno"].pk]


def test_il_membro_usa_l_area_ma_non_la_gestisce(client, a, settings):
    settings.AI_TURNI_SINCRONI = True
    MembroArea.objects.create(progetto=a["area"], utente=a["bruno"])
    client.force_login(a["bruno"])
    pagina = client.get(reverse("ai:progetto", args=[a["area"].pk])).content.decode()
    assert "Offerta Rossi" in pagina and "condivisa con te" in pagina and reverse("ai:progetti_modifica", args=[a["area"].pk]) not in pagina
    assert client.get(reverse("ai:progetti_modifica", args=[a["area"].pk])).status_code in (403, 404)
    assert client.post(reverse("ai:collega", args=[a["area"].pk]), {"ct": 1, "record": 1}).status_code == 404
    client.post(reverse("ai:invia"), {"testo": "domanda di Bruno", "progetto": a["area"].pk})
    chat = Conversazione.objects.get(messaggi__testo="domanda di Bruno")
    assert chat.progetto == a["area"] and chat.utente == a["bruno"]
    assert "Tono formale." in contesto_utente.nota_progetto(chat)                       # istruzioni comuni


def test_chat_private_e_condivise(client, a):
    MembroArea.objects.create(progetto=a["area"], utente=a["bruno"])
    privata = Conversazione.objects.create(utente=a["bruno"], titolo="Bozza privata di Bruno", progetto=a["area"])
    condivisa = Conversazione.objects.create(utente=a["bruno"], titolo="Analisi condivisa", progetto=a["area"], condivisa=True)
    albero = client.get(reverse("ai:albero_progetto", args=[a["area"].pk])).content.decode()
    assert "Analisi condivisa" in albero and "Bozza privata" not in albero and "Bruno" in albero
    assert client.get(reverse("ai:conversazione", args=[privata.pk])).status_code == 404
    from html import unescape
    pagina = unescape(client.get(reverse("ai:conversazione", args=[condivisa.pk])).content.decode())
    assert "data-sola-lettura" in pagina and "condivisa con l'area di lavoro" in pagina and 'class="ai-fondo" hidden' in pagina
    assert client.post(reverse("ai:invia_conversazione", args=[condivisa.pk]), {"testo": "scrivo io"}).status_code == 404
    assert client.post(reverse("ai:condividi_chat", args=[condivisa.pk])).status_code == 404     # solo chi l'ha scritta
    gestione = client.get(reverse("ai:progetti_dettaglio", args=[a["area"].pk])).content.decode()
    assert "Analisi condivisa" in gestione and "Bozza privata" not in gestione


def test_condividere_una_propria_chat(client, a):
    mia = Conversazione.objects.create(utente=a["u"], titolo="Mia", progetto=a["area"])
    client.post(reverse("ai:condividi_chat", args=[mia.pk]))
    mia.refresh_from_db()
    assert mia.condivisa
    fuori = Conversazione.objects.create(utente=a["u"], titolo="Fuori")
    assert client.post(reverse("ai:condividi_chat", args=[fuori.pk])).status_code == 404       # solo chat di un'area


def test_chi_esce_perde_l_accesso(client, a):
    MembroArea.objects.create(progetto=a["area"], utente=a["bruno"])
    chat = Conversazione.objects.create(utente=a["bruno"], titolo="Sua", progetto=a["area"], condivisa=True)
    attivita = Pianificata.objects.create(utente=a["bruno"], azienda=a["az"], nome="x", istruzioni="x", ricorrenza="giorni", alle=ora(9), progetto=a["area"])
    aree.imposta_membri(a["area"], [])
    chat.refresh_from_db()
    attivita.refresh_from_db()
    assert chat.progetto is None and not chat.condivisa and attivita.progetto is None
    client.force_login(a["bruno"])
    assert client.get(reverse("ai:progetto", args=[a["area"].pk])).status_code == 404
    assert client.get(reverse("ai:albero_progetto", args=[a["area"].pk])).status_code == 404


def test_un_altra_azienda_non_vede(client, a):
    MembroArea.objects.create(progetto=a["area"], utente=a["fuori"])                    # anche se finisse tra i membri
    client.force_login(a["fuori"])
    assert client.get(reverse("ai:progetto", args=[a["area"].pk])).status_code == 404
