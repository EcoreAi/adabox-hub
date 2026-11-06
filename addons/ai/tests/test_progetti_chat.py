"""La pagina del progetto nella chat: chat, documenti, grafici e file per tipo; colonna di sinistra, percorso, cronologia."""
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from ai import documenti_chat
from ai.models import Artifact, Conversazione, ProgettoChat
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)


def _progetto(s, nome="Sviluppo AdaV3", **extra):
    return ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome=nome, **extra)


def test_pagina_del_progetto(client, s):
    p = _progetto(s, istruzioni="Rispondi breve.")
    c = Conversazione.objects.create(utente=s["u"], titolo="Specifica voce", progetto=p)
    fuori = Conversazione.objects.create(utente=s["u"], titolo="Chat fuori")
    documenti_chat.crea(c, s["u"], s["az"], "Note di rilascio", "testo")
    Artifact.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], tipo="grafico", titolo="Ticket per mese")
    Artifact.objects.create(conversazione=fuori, utente=s["u"], azienda=s["az"], tipo="tabella", titolo="Altro")
    pagina = client.get(reverse("ai:progetto", args=[p.pk])).content.decode()
    for testo in ("Sviluppo AdaV3", "Rispondi breve.", "Specifica voce", "Note di rilascio", "Ticket per mese", 'name="progetto" value="%d"' % p.pk,
                  reverse("ai:progetti_modifica", args=[p.pk]), "allegati/elenco/"):
        assert testo in pagina, testo
    centro = pagina.split('class="ai-progetto-sezioni"')[1]
    assert "Chat fuori" not in centro and "Altro" not in centro
    assert 'data-suggerimenti' not in pagina                                     # al posto dei suggerimenti


def test_progetto_di_altri_o_di_un_altra_azienda(client, s):
    altro = User.objects.create_user("bruno", password="x")
    loro = ProgettoChat.objects.create(utente=altro, azienda=s["az"], nome="Loro")
    altra_azienda = ProgettoChat.objects.create(utente=s["u"], azienda=s["altra"], nome="Altrove")
    assert client.get(reverse("ai:progetto", args=[loro.pk])).status_code == 404
    assert client.get(reverse("ai:progetto", args=[altra_azienda.pk])).status_code == 404


def test_colonna_di_sinistra_percorso_e_cronologia(client, s):
    p = _progetto(s)
    chat = [Conversazione.objects.create(utente=s["u"], titolo=f"Chat {i}", progetto=p) for i in range(5)]
    pagina = client.get(reverse("ai:conversazione", args=[chat[0].pk])).content.decode()
    pannello = pagina.split('data-contenuto="progetti"')[1].split("</section>")[0]
    assert reverse("ai:progetto", args=[p.pk]) in pannello and pannello.count('class="ai-progetto-chat"') == 1
    assert sum(f"Chat {i}<" in pannello for i in range(5)) == 3                                 # le ultime tre
    assert 'class="ai-percorso"' in pagina and pagina.split('class="ai-percorso"')[1].split("</nav>")[0].count("Sviluppo AdaV3") == 1
    storico = pagina.split('id="ai-elenco-storico"')[1].split("</ul>")[0]
    assert "ai-elenco-progetto" in storico and "Sviluppo AdaV3" in storico


def test_chip_del_progetto_con_la_x_e_prima_chat(client, s, settings):
    settings.AI_TURNI_SINCRONI = True
    p = _progetto(s)
    pagina = client.get(f"{reverse('ai:chat')}?progetto={p.pk}").content.decode()
    chip = pagina.split('class="ai-chip ai-chip-progetto"')[1].split("</span>")[0]
    assert "Sviluppo AdaV3" in chip and f'href="{reverse("ai:chat")}"' in chip and "Esci dal progetto" in chip
    client.post(reverse("ai:invia"), {"testo": "prima domanda", "progetto": p.pk})
    assert Conversazione.objects.get(messaggi__testo="prima domanda").progetto == p
