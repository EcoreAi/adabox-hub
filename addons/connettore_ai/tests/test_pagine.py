from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from connettore_ai import lavori
from connettore_ai.models import ChatCollegata, Chiamata, ClientOAuth, Codice, Token
from core import parametri

from .conftest import CLAUDE, MCP, chiama, persona, rpc


def test_indirizzi_alla_radice_dichiarati_dal_modulo():
    assert reverse("connettore_ai_mcp") == "/mcp"
    assert reverse("connettore_ai_metadati_risorsa") == "/.well-known/oauth-protected-resource/mcp"
    assert reverse("connettore_ai_metadati_server") == "/.well-known/oauth-authorization-server"
    assert reverse("connettore_ai:token") == "/connettore_ai/oauth/token"


def test_le_mie_chat_elenco_e_scollega(client, collegata, mario, azienda, contatti):
    chiama(client, collegata["access_token"], "cerca_record", {"vista": "contatti.contatti"})
    client.force_login(mario)
    html = client.get("/connettore_ai/").content.decode()
    assert MCP in html and "Claude" in html and "1 chiamate" in html and "tutte le app che vedi" in html
    assert "connectorUrl=https%3A%2F%2Fhub.esempio.it%2Fmcp" in html                        # il link che apre Claude già compilato
    collegamento = ChatCollegata.objects.get()
    altro = persona("lucia", azienda)
    client.force_login(altro)
    assert "Nessuna chat collegata" in client.get("/connettore_ai/").content.decode()
    assert client.post(f"/connettore_ai/scollega/{collegamento.pk}/").status_code == 404     # non è suo
    client.force_login(mario)
    assert client.get(f"/connettore_ai/scollega/{collegamento.pk}/").status_code == 405
    assert client.post(f"/connettore_ai/scollega/{collegamento.pk}/").status_code == 302
    collegamento.refresh_from_db()
    assert collegamento.revocato is not None and collegamento.revocato_da == mario and not Token.objects.exists()
    assert rpc(client, collegata["access_token"], "tools/list").status_code == 401
    assert "Nessuna chat collegata" in client.get("/connettore_ai/").content.decode()


def test_pagina_quando_l_azienda_non_ha_acceso(client, mario, azienda):
    parametri.scrivi("connettore_ai.attivo", False, azienda)
    client.force_login(mario)
    html = client.get("/connettore_ai/").content.decode()
    assert "non ha acceso" in html and MCP not in html
    senza = User.objects.create_user("ospite", "o@example.com", "pass12345!")
    client.force_login(senza)
    assert client.get("/connettore_ai/").status_code == 403


def test_elenchi_dell_amministratore_in_sola_lettura(client, collegata, superuser, azienda, contatti):
    chiama(client, collegata["access_token"], "cerca_record", {"vista": "contatti.contatti"})
    superuser.profilo.aziende.set([azienda])
    superuser.profilo.azienda_predefinita = azienda
    superuser.profilo.save()
    client.force_login(superuser)
    collegamento = ChatCollegata.objects.get()
    for percorso in ("/connettore_ai/collegamenti/", "/connettore_ai/chiamate/", "/connettore_ai/client/",
                     f"/connettore_ai/collegamenti/{collegamento.pk}/", f"/connettore_ai/chiamate/{Chiamata.objects.get().pk}/"):
        assert client.get(percorso).status_code == 200, percorso
    assert client.get("/connettore_ai/collegamenti/nuovo/").status_code in (403, 404)
    assert client.post(f"/connettore_ai/collegamenti/{collegamento.pk}/bottone/scollega/").status_code == 302
    collegamento.refresh_from_db()
    assert collegamento.revocato_da == superuser
    assert rpc(client, collegata["access_token"], "tools/list").status_code == 401


def test_le_viste_del_connettore_non_arrivano_alle_chat(client, collegata, mario):
    from django.contrib.auth.models import Permission
    mario.user_permissions.add(*Permission.objects.filter(content_type__app_label="connettore_ai"))
    testo = chiama(client, collegata["access_token"], "elenco_viste")["content"][0]["text"]
    assert "connettore_ai" not in testo


def test_pulizia(collegata, mario, azienda):
    adesso = timezone.now()
    collegamento = ChatCollegata.objects.get()
    client_usato = collegamento.client
    mai_usato = ClientOAuth.objects.create(client_id="cai_c_vecchio", tipo=ClientOAuth.DCR, redirect_uris=[CLAUDE])
    recente = ClientOAuth.objects.create(client_id="cai_c_recente", tipo=ClientOAuth.DCR, redirect_uris=[CLAUDE])
    ClientOAuth.objects.filter(pk=mai_usato.pk).update(creato=adesso - timedelta(days=30))
    Codice.objects.update(scade=adesso - timedelta(days=2))
    Chiamata.objects.create(collegamento=collegamento, azienda=azienda, utente=mario, strumento="x", esito=Chiamata.FATTA)
    Chiamata.objects.update(creato=adesso - timedelta(days=400))
    lavori.pulisci()
    assert not Codice.objects.exists() and not Chiamata.objects.exists()
    assert set(ClientOAuth.objects.values_list("pk", flat=True)) == {client_usato.pk, recente.pk}
    assert ChatCollegata.objects.get().attivo and Token.objects.count() == 2
    # 90 giorni senza uso: i token scadono, il collegamento resta nello storico come scollegato
    Token.objects.update(scade=adesso - timedelta(seconds=1))
    ChatCollegata.objects.update(creato=adesso - timedelta(days=91))
    assert lavori.pulisci() == "1 collegamenti scaduti"
    assert not Token.objects.exists() and not ChatCollegata.objects.get().attivo
