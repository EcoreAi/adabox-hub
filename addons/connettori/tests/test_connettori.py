"""Avvisi firmati verso l'esterno, tentativi, sicurezza dell'indirizzo, collegamenti ai record esterni, bottoni via API."""
import hashlib
import hmac
import json
from unittest import mock

import httpx2 as httpx
import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from connettori import consegne, eventi, riferimenti
from connettori.models import ConsegnaWebhook, RiferimentoEsterno, Webhook
from contatti.models import Contatto
from core import rete
from core.models import Azienda, TokenApi

pytestmark = pytest.mark.django_db(transaction=True)


class Ricevitore:
    """Un client httpx finto: ricorda le richieste e risponde con gli stati dati."""

    def __init__(self, *stati):
        self.stati, self.richieste = list(stati) or [200], []
        self.client = httpx.Client(transport=httpx.MockTransport(self._rispondi))

    def _rispondi(self, richiesta):
        self.richieste.append(richiesta)
        stato = self.stati.pop(0) if len(self.stati) > 1 else self.stati[0]
        return httpx.Response(stato)


@pytest.fixture
def ricevitore(monkeypatch):
    r = Ricevitore()
    monkeypatch.setattr(consegne, "HTTP", r.client)
    monkeypatch.setattr(rete.socket, "getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", ("93.184.216.34", p))])
    return r


@pytest.fixture
def azienda():
    return Azienda.objects.first() or Azienda.objects.create(nome="Azienda A")


def _webhook(azienda, eventi_="contatti.contatto.*", **extra):
    return Webhook.objects.create(azienda=azienda, nome="CRM", url="https://crm.example.com/hook?x=1", eventi=eventi_, **extra)


def test_creazione_spedisce_un_avviso_firmato(azienda, ricevitore):
    w = _webhook(azienda)
    c = Contatto.objects.create(azienda=azienda, nome="Rossi Srl")
    assert len(ricevitore.richieste) == 1
    r = ricevitore.richieste[0]
    corpo = json.loads(r.content)
    assert corpo["evento"] == "contatti.contatto.creato" and corpo["dati"]["nome"] == "Rossi Srl" and corpo["dati"]["id"] == c.pk
    assert corpo["azienda"] == azienda.pk and r.headers["X-Adabox-Consegna"] == corpo["id"]
    t, v1 = [p.split("=", 1)[1] for p in r.headers["X-Adabox-Firma"].split(",")]
    assert v1 == hmac.new(w.segreto().encode(), f"{t}.".encode() + r.content, hashlib.sha256).hexdigest()
    assert ConsegnaWebhook.objects.get().stato == ConsegnaWebhook.CONSEGNATA


def test_si_collega_all_ip_controllato_con_l_host_giusto(azienda, ricevitore):
    _webhook(azienda)
    Contatto.objects.create(azienda=azienda, nome="X")
    r = ricevitore.richieste[0]
    assert r.url.host == "93.184.216.34" and r.url.path == "/hook" and r.url.query == b"x=1"
    assert r.headers["Host"] == "crm.example.com" and r.extensions["sni_hostname"] == "crm.example.com"


def test_aggiornamento_ed_eliminazione(azienda, ricevitore):
    _webhook(azienda)
    c = Contatto.objects.create(azienda=azienda, nome="X")
    pk = c.pk
    c.nome = "Y"
    c.save()
    c.delete()
    corpi = [json.loads(r.content) for r in ricevitore.richieste]
    assert [x["evento"].rsplit(".", 1)[1] for x in corpi] == ["creato", "aggiornato", "eliminato"]
    assert corpi[1]["dati"]["nome"] == "Y" and corpi[2]["dati"] == {"id": pk}


def test_solo_gli_eventi_ascoltati_e_solo_la_propria_azienda(azienda, ricevitore):
    altra = Azienda.objects.create(nome="Altra")
    _webhook(azienda, "contatti.contatto.eliminato")
    _webhook(altra)
    Contatto.objects.create(azienda=azienda, nome="X")
    assert not ricevitore.richieste


def test_i_modelli_fuori_dall_api_non_escono(azienda, ricevitore):
    from helpdesk.models import FaseTicket
    _webhook(azienda, "*")
    FaseTicket.objects.create(nome="Nuova")
    assert not ricevitore.richieste


def test_webhook_spento_non_riceve(azienda, ricevitore):
    _webhook(azienda, attivo=False)
    Contatto.objects.create(azienda=azienda, nome="X")
    assert not ricevitore.richieste


def test_senza_eventi_non_si_rimanda_ciò_che_arriva_da_fuori(azienda, ricevitore):
    _webhook(azienda)
    with eventi.senza_eventi():
        Contatto.objects.create(azienda=azienda, nome="X")
    assert not ricevitore.richieste


def test_errore_lascia_la_consegna_da_ritentare_e_poi_riesce(azienda, ricevitore):
    w = _webhook(azienda)
    ricevitore.stati[:] = [500, 200]
    Contatto.objects.create(azienda=azienda, nome="X")
    c = ConsegnaWebhook.objects.get()
    assert c.stato == ConsegnaWebhook.IN_CODA and c.risposta == 500 and c.tentativi == 1 and "500" in c.errore
    w.refresh_from_db()
    assert w.fallimenti_di_fila == 1
    consegne.invia(c.pk)
    c.refresh_from_db()
    w.refresh_from_db()
    assert c.stato == ConsegnaWebhook.CONSEGNATA and c.errore == "" and w.fallimenti_di_fila == 0


def test_dopo_cinque_tentativi_fallisce(azienda, ricevitore):
    ricevitore.stati[:] = [500]
    _webhook(azienda)
    Contatto.objects.create(azienda=azienda, nome="X")
    c = ConsegnaWebhook.objects.get()
    for _ in range(4):
        with pytest.raises(consegne.NonConsegnata):
            consegne.invia(c.pk)
    c.refresh_from_db()
    assert c.stato == ConsegnaWebhook.FALLITA and c.tentativi == 5


def test_troppi_fallimenti_di_fila_spengono_il_webhook(azienda, ricevitore):
    ricevitore.stati[:] = [500]
    w = _webhook(azienda)
    Webhook.objects.filter(pk=w.pk).update(fallimenti_di_fila=consegne.MAX_FALLIMENTI_DI_FILA - 1)
    Contatto.objects.create(azienda=azienda, nome="X")
    w.refresh_from_db()
    assert not w.attivo and w.disattivato_il is not None


def test_consegne_doppie_in_coda_si_uniscono(azienda, ricevitore):
    w = _webhook(azienda)
    c = Contatto.objects.create(azienda=azienda, nome="X")
    ct = ContentType.objects.get_for_model(Contatto)
    prima = ConsegnaWebhook.objects.create(webhook=w, azienda=azienda, evento="contatti.contatto.aggiornato", content_type=ct, object_id=c.pk)
    n = ConsegnaWebhook.objects.count()
    assert eventi._crea(w, prima.evento, ct, c.pk) is None and ConsegnaWebhook.objects.count() == n


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "::1"])
def test_indirizzi_interni_rifiutati_senza_chiamata(azienda, ricevitore, monkeypatch, ip):
    monkeypatch.setattr(rete.socket, "getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", (ip, p))])
    _webhook(azienda)
    Contatto.objects.create(azienda=azienda, nome="X")
    assert not ricevitore.richieste
    assert "rifiutato" in ConsegnaWebhook.objects.get().errore.lower()


@pytest.mark.parametrize("url", ["http://crm.example.com/", "https://u:p@crm.example.com/", "https://crm.example.com:8443/", "ftp://x.example.com/"])
def test_il_form_rifiuta_indirizzi_non_ammessi(azienda, url):
    with pytest.raises(ValidationError):
        Webhook(azienda=azienda, nome="X", url=url, eventi="*").full_clean()


def test_la_chiave_e_cifrata_nel_database(azienda):
    w = _webhook(azienda)
    assert w.segreto() and w.segreto() not in w.segreto_cifrato


def test_la_prova_arriva(azienda, ricevitore):
    eventi.prova(_webhook(azienda))
    assert json.loads(ricevitore.richieste[0].content)["evento"] == "connettori.prova"


def test_riferimenti_nei_due_sensi_e_per_azienda(azienda):
    altra = Azienda.objects.create(nome="Altra")
    c = Contatto.objects.create(azienda=azienda, nome="X")
    riferimenti.collega(c, "hubspot", 123)
    assert riferimenti.id_esterno(c, "hubspot") == "123"
    assert riferimenti.trova(Contatto, azienda, "hubspot", "123") == c
    assert riferimenti.trova(Contatto, altra, "hubspot", "123") is None
    riferimenti.collega(c, "hubspot", 456)
    assert riferimenti.id_esterno(c, "hubspot") == "456" and RiferimentoEsterno.objects.count() == 1


def test_non_si_collega_un_record_di_un_altra_azienda(azienda):
    altra = Azienda.objects.create(nome="Altra")
    c = Contatto.objects.create(azienda=altra, nome="X")
    rif = RiferimentoEsterno(azienda=azienda, sistema="hubspot", content_type=ContentType.objects.get_for_model(Contatto),
                             object_id=c.pk, id_esterno="1")
    with pytest.raises(ValidationError):
        rif.full_clean()


def _utente(azienda, *permessi):
    u = User.objects.create_user("u", "u@example.com", "x")
    u.user_permissions.add(*Permission.objects.filter(codename__in=permessi))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


def test_filtro_api_per_identificativo_esterno(client, azienda):
    c = Contatto.objects.create(azienda=azienda, nome="X")
    riferimenti.collega(c, "hubspot", "abc")
    _, token = TokenApi.genera(_utente(azienda, "view_riferimentoesterno"), "p")
    r = client.get("/api/v1/connettori/riferimenti/?q=abc", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert r.status_code == 200 and r.json()["results"][0]["object_id"] == c.pk


def test_bottone_via_api_rispetta_permessi_e_stato(client, azienda):
    from todo.models import Attivita
    a = Attivita.objects.create(azienda=azienda, titolo="X")
    vista_bottoni = __import__("core.viste", fromlist=["registry"]).registry.per_modello(Attivita).buttons
    assert vista_bottoni, "serve una vista con bottoni"
    nome = vista_bottoni[0]
    _, senza = TokenApi.genera(_utente(azienda, "view_attivita"), "p")
    url = f"/api/v1/todo/attivita/{a.pk}/azioni/{nome}/"
    assert client.post(url, HTTP_AUTHORIZATION=f"Bearer {senza}").status_code == 404
    assert client.post(f"/api/v1/todo/attivita/{a.pk}/azioni/inventata/", HTTP_AUTHORIZATION=f"Bearer {senza}").status_code == 404
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    _, pieno = TokenApi.genera(root, "q")
    r = client.post(url, HTTP_AUTHORIZATION=f"Bearer {pieno}")
    assert r.status_code == 200 and "esito" in r.json() and r.json()["dati"]["id"] == a.pk


def test_bottone_via_api_non_tocca_altre_aziende(client, azienda):
    from todo.models import Attivita
    altra = Azienda.objects.create(nome="Altra")
    a = Attivita.objects.create(azienda=altra, titolo="X")
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    _, token = TokenApi.genera(root, "q")
    assert client.post(f"/api/v1/todo/attivita/{a.pk}/azioni/qualsiasi/", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 404


def test_pagina_del_webhook_mostra_la_chiave_solo_a_chi_puo_modificare(client, azienda):
    w = _webhook(azienda)
    client.force_login(_utente(azienda, "view_webhook"))
    assert w.segreto() not in client.get(f"/connettori/webhook/{w.pk}/").content.decode()
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    client.force_login(root)
    assert w.segreto() in client.get(f"/connettori/webhook/{w.pk}/").content.decode()


def test_webhook_di_altra_azienda_non_si_apre(client, azienda):
    altra = Azienda.objects.create(nome="Altra")
    w = _webhook(altra)
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([azienda])
    client.force_login(root)
    assert client.get(f"/connettori/webhook/{w.pk}/").status_code == 404
