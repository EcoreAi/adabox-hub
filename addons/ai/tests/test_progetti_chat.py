"""La pagina del progetto nella chat: chat, documenti, grafici e file per tipo; colonna di sinistra, percorso, cronologia."""
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from ai import documenti_chat
from ai.models import Artifact, Conversazione, ProgettoChat
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)


def _progetto(s, nome="Sviluppo AdaV3", **extra):
    return ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome=nome, **extra)


def test_pagina_del_progetto(client, s):
    """Titolo, istruzioni e casella: chat, documenti, grafici e file stanno nell'albero a sinistra, non in card."""
    p = _progetto(s, istruzioni="Rispondi breve.")
    Conversazione.objects.create(utente=s["u"], titolo="Specifica voce", progetto=p)
    pagina = client.get(reverse("ai:progetto", args=[p.pk])).content.decode()
    for testo in ("Sviluppo AdaV3", "Rispondi breve.", 'name="progetto" value="%d"' % p.pk, reverse("ai:progetti_modifica", args=[p.pk]),
                  "ai-progetto-guida", reverse("ai:albero_progetto", args=[p.pk])):
        assert testo in pagina, testo
    assert "ai-progetto-sezioni" not in pagina and 'data-suggerimenti' not in pagina


def test_progetto_di_altri_o_di_un_altra_azienda(client, s):
    altro = User.objects.create_user("bruno", password="x")
    loro = ProgettoChat.objects.create(utente=altro, azienda=s["az"], nome="Loro")
    altra_azienda = ProgettoChat.objects.create(utente=s["u"], azienda=s["altra"], nome="Altrove")
    assert client.get(reverse("ai:progetto", args=[loro.pk])).status_code == 404
    assert client.get(reverse("ai:progetto", args=[altra_azienda.pk])).status_code == 404


def test_colonna_di_sinistra_percorso_e_cronologia(client, s):
    p = _progetto(s)
    altro = _progetto(s, nome="Altro progetto")
    chat = [Conversazione.objects.create(utente=s["u"], titolo=f"Chat {i}", progetto=p) for i in range(5)]
    pagina = client.get(reverse("ai:conversazione", args=[chat[0].pk])).content.decode()
    pannello = pagina.split('data-contenuto="progetti"')[1].split("</section>")[0]
    assert reverse("ai:progetto", args=[p.pk]) in pannello and "data-in-progetto" in pagina
    voce = pannello.split(f'{reverse("ai:albero_progetto", args=[p.pk])}?chat={chat[0].pk}"')[1].split(">")[0]
    assert "open" in voce                                                           # il progetto della chat è aperto
    assert " open" not in pannello.split(reverse("ai:albero_progetto", args=[altro.pk]))[1].split(">")[0]
    barra = pagina.split('class="ai-barra-area"')[1].split("</div>")[0]
    assert f'value="{p.pk}" selected' in barra and "Sviluppo AdaV3" in barra
    storico = pagina.split('id="ai-elenco-storico"')[1].split("</ul>")[0]
    assert "ai-elenco-progetto" in storico and "Sviluppo AdaV3" in storico
    assert "data-in-progetto" not in client.get(reverse("ai:chat")).content.decode()


def test_sottocartelle_del_progetto(client, s):
    from core import allegati
    from django.core.files.uploadedfile import SimpleUploadedFile
    p = _progetto(s)
    chat = [Conversazione.objects.create(utente=s["u"], titolo=f"Chat {i}", progetto=p) for i in range(10)]
    documenti_chat.crea(chat[0], s["u"], s["az"], "Note di rilascio", "testo")
    Artifact.objects.create(conversazione=chat[0], utente=s["u"], azienda=s["az"], tipo="grafico", titolo="Per stato", salvato=True)
    allegati.salva(p, SimpleUploadedFile("specifica.txt", b"testo"), s["u"])
    from html import unescape
    html = unescape(client.get(f"{reverse('ai:albero_progetto', args=[p.pk])}?chat={chat[3].pk}").content.decode())
    gruppi = html.split('class="ai-albero-gruppo"')[1:]
    assert [g.split("<span>")[1].split("</span>")[0] for g in gruppi] == ["Chat", "Documenti", "Grafici e tabelle", "File"]
    assert ' open' in gruppi[0].split(">")[0] and gruppi[0].count("<li>") == 10                 # tutte, l'elenco scorre
    assert 'class="is-attiva"' in gruppi[0] and "data-corrente" in gruppi[0] and "Note di rilascio" in gruppi[1] and "★ Per stato" in gruppi[2]
    assert "specifica.txt" in gruppi[3] and "solo dell'area" in gruppi[3]
    assert all("data-elimina" in g for g in gruppi) and 'data-carica-albero="cartella"' in gruppi[3] and "i file dell'area" in gruppi[3]
    altro = User.objects.create_user("bruno", password="x")
    altro.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    client.force_login(altro)
    assert client.get(reverse("ai:albero_progetto", args=[p.pk])).status_code == 404


def test_carica_ed_elimina_dall_albero_senza_cartella(client, s):
    from core.models import Allegato
    from django.core.files.uploadedfile import SimpleUploadedFile
    from ai.models import DocumentoChat
    p = _progetto(s)
    r = client.post(reverse("ai:carica_archivio", args=[p.pk]), {"file": [SimpleUploadedFile("a.txt", b"uno"), SimpleUploadedFile("b.txt", b"due")]})
    assert r.json() == {"caricati": 2, "errori": []} and Allegato.objects.filter(object_id=p.pk).count() == 2
    c = Conversazione.objects.create(utente=s["u"], titolo="x", progetto=p)
    d = documenti_chat.crea(c, s["u"], s["az"], "Bozza", "testo")
    a = Artifact.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], tipo="tabella", titolo="T")
    assert client.post(reverse("ai:elimina_elemento", args=["documento", d.pk])).json() == {"ok": True}
    assert client.post(reverse("ai:elimina_elemento", args=["artifact", a.pk])).json() == {"ok": True}
    assert not DocumentoChat.objects.exists() and not Artifact.objects.exists()
    altro = User.objects.create_user("bruno", password="x")
    altro.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    d2 = documenti_chat.crea(c, s["u"], s["az"], "Altra", "testo")
    client.force_login(altro)
    assert client.post(reverse("ai:elimina_elemento", args=["documento", d2.pk])).status_code == 404
    assert client.post(reverse("ai:carica_archivio", args=[p.pk]), {"file": [SimpleUploadedFile("c.txt", b"x")]}).status_code == 404


def test_chip_del_progetto_con_la_x_e_prima_chat(client, s, settings):
    settings.AI_TURNI_SINCRONI = True
    p = _progetto(s)
    pagina = client.get(f"{reverse('ai:chat')}?progetto={p.pk}").content.decode()
    barra = pagina.split('class="ai-barra-area"')[1].split("</div>")[0]
    assert f'value="{p.pk}" selected' in barra and f'name="progetto" value="{p.pk}"' in pagina   # la chat nuova nasce lì
    client.post(reverse("ai:invia"), {"testo": "prima domanda", "progetto": p.pk})
    assert Conversazione.objects.get(messaggi__testo="prima domanda").progetto == p


def test_albero_con_molte_chat_senza_barre(client, s):
    """Oltre 8 voci per gruppo le altre stanno dietro «Mostra altre N», aperto se la chat corrente è tra quelle."""
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Grande")
    chat = [Conversazione.objects.create(utente=s["u"], titolo=f"Chat {i:02d}", progetto=p) for i in range(11)]
    html = client.get(reverse("ai:albero_progetto", args=[p.pk])).content.decode()
    gruppo = html.split('data-gruppo="chat"')[1].split("</details>\n")[0]
    assert "Mostra altre 3" in gruppo and gruppo.count("<li>") == 11 and 'class="ai-albero-altre" open' not in gruppo
    vecchia = min(chat, key=lambda c: c.aggiornata)                                  # in fondo all'elenco
    html = client.get(f"{reverse('ai:albero_progetto', args=[p.pk])}?chat={vecchia.pk}").content.decode()
    assert 'class="ai-albero-altre" open' in html
