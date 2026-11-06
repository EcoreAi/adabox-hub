import datetime
import json

import pytest
from django.contrib.auth.models import Permission, User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.models import Modulo, Parametro
from discuss import chiamate, servizi
from discuss.models import Canale, Chiamata, Evento, Partecipante, Segnale


def _utente(nome):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="discuss", codename__in=["view_canale", "add_canale", "add_messaggio"]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def persone(db):
    return _utente("anna"), _utente("bruno"), _utente("carla")


def _righe(risposta):
    testo = b"".join(risposta.streaming_content).decode()
    return [json.loads(r[6:]) for r in testo.splitlines() if r.startswith("data: ") and r != "data: {}"]


def _flusso(client, c, p, dopo=0):
    return _righe(client.get(reverse("discuss:chiamata_eventi", args=[c.token]), {"s": p.segreto, "dopo": dopo}))


def test_avvia_entra_e_collegati(client, persone):
    anna, bruno, carla = persone
    diretto = servizi.diretto([anna, bruno])
    client.force_login(anna)
    r = client.post(reverse("discuss:chiama", args=[diretto.pk]), {"video": "1"})
    c = Chiamata.objects.get()
    assert r.url == reverse("discuss:chiamata", args=[c.token]) and c.video and c.avviata_da == anna
    # squilla solo perché è un messaggio diretto; un secondo clic entra nella stessa chiamata
    assert Evento.objects.get(tipo="chiamata").dati["squilla"] is True and Evento.objects.get(tipo="chiamata").dati["url"] == r.url
    client.post(reverse("discuss:chiama", args=[diretto.pk]))
    assert Chiamata.objects.count() == 1
    assert chiamate.squilli_per(bruno) == [c] and chiamate.squilli_per(anna) == [] and chiamate.squilli_per(carla) == []
    assert "Rispondi" not in client.get("/").content.decode() and client.get(r.url).status_code == 200
    a = client.post(reverse("discuss:chiamata_entra", args=[c.token])).json()
    assert a["ammesso"] and a["altri"] == [] and a["ice"][0]["urls"].startswith("stun:")
    b_client = Client()
    b_client.force_login(bruno)
    html = b_client.get("/discuss/contatore/").content.decode()
    assert f'data-ds-squillo="{c.token}"' in html
    b = b_client.post(reverse("discuss:chiamata_entra", args=[c.token])).json()
    assert [x["nome"] for x in b["altri"]] == ["Anna"]
    assert chiamate.squilli_per(bruno) == []                                      # entrato: smette di squillare
    pa, pb = Partecipante.objects.get(pk=a["io"]), Partecipante.objects.get(pk=b["io"])
    # anna sa che è entrato bruno; le offerte vanno solo a chi sono indirizzate
    assert any(s["tipo"] == "entrato" and s["nome"] == "Bruno" for s in _flusso(client, c, pa))
    url = reverse("discuss:chiamata_segnale", args=[c.token])
    assert b_client.post(url, json.dumps({"a": pa.pk, "tipo": "offerta", "corpo": {"type": "offer", "sdp": "x"}}), content_type="application/json", headers={"X-Segreto": pb.segreto}).status_code == 204
    assert any(s["tipo"] == "offerta" and s["corpo"]["sdp"] == "x" and s["id"] == pb.pk for s in _flusso(client, c, pa))
    assert not any(s["tipo"] == "offerta" for s in _flusso(client, c, pb))
    # senza segreto, o con quello di un'altra chiamata, niente
    anonimo = Client(enforce_csrf_checks=True)
    assert anonimo.post(url, "{}", content_type="application/json").status_code == 403
    assert anonimo.get(reverse("discuss:chiamata_eventi", args=[c.token]), {"s": "falso"}).status_code == 403
    # tipi inventati non passano
    Segnale.objects.all().delete()
    b_client.post(url, json.dumps({"a": pa.pk, "tipo": "fine"}), content_type="application/json", headers={"X-Segreto": pb.segreto})
    assert not Segnale.objects.exists()
    # microfono, mano
    b_client.post(reverse("discuss:chiamata_stato", args=[c.token]), json.dumps({"mano": True, "microfono": False, "nome": "Finto"}), content_type="application/json", headers={"X-Segreto": pb.segreto})
    stato = next(s for s in _flusso(client, c, pa) if s["tipo"] == "stato")
    assert stato["mano"] is True and stato["microfono"] is False and stato["nome"] == "Bruno"
    # si esce: l'ultimo chiude e la conversazione lo dice
    b_client.post(reverse("discuss:chiamata_esci", args=[c.token]), headers={"X-Segreto": pb.segreto})
    assert any(s["tipo"] == "uscito" for s in _flusso(client, c, pa)) and Chiamata.objects.get().finita is None
    client.post(reverse("discuss:chiamata_esci", args=[c.token]), pa.segreto, content_type="text/plain")      # sendBeacon
    c.refresh_from_db()
    assert c.finita is not None and diretto.messaggi.filter(corpo__startswith="Chiamata terminata").exists()
    assert Evento.objects.filter(tipo="chiamata_fine").exists()
    assert "terminata" in client.get(reverse("discuss:chiamata", args=[c.token])).content.decode()


def test_chi_non_c_entra_resta_fuori(client, persone):
    anna, bruno, carla = persone
    privato = servizi.crea_canale("segreto", Canale.PRIVATO, anna, [bruno])
    c = chiamate.avvia(privato, anna)
    client.force_login(carla)
    assert client.post(reverse("discuss:chiama", args=[privato.pk])).status_code == 404
    assert client.get(reverse("discuss:chiamata", args=[c.token])).status_code == 404
    assert client.post(reverse("discuss:chiamata_entra", args=[c.token])).status_code == 403
    assert client.post(reverse("discuss:chiamata_ospiti", args=[c.token]), {"si": "1"}).status_code == 403
    # senza login: al login, se la chiamata non è aperta agli ospiti
    r = Client().get(reverse("discuss:chiamata", args=[c.token]))
    assert r.status_code == 302 and "next=" in r.url


def test_ospite_esterno_aspetta_e_non_sente_nulla_finche_non_e_ammesso(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("segreto", Canale.PRIVATO, anna, [bruno])
    c = chiamate.avvia(canale, anna)
    client.force_login(anna)
    pa = Partecipante.objects.get(pk=client.post(reverse("discuss:chiamata_entra", args=[c.token])).json()["io"])
    assert client.post(reverse("discuss:chiamata_ospiti", args=[c.token]), {"si": "1"}).json() == {"ospiti": True}
    ospite = Client()
    pagina = ospite.get(reverse("discuss:chiamata", args=[c.token]))
    html = pagina.content.decode()
    assert pagina.status_code == 200 and "segreto" not in html.split("<title>")[1].split("</title>")[0] and "Il tuo nome" in html
    assert 'data-link' not in html and "Anna" not in html
    url = reverse("discuss:chiamata_entra", args=[c.token])
    assert ospite.post(url, {"nome": " "}).status_code == 422
    g = ospite.post(url, {"nome": "Giulia Esterna"}).json()
    pg = Partecipante.objects.get(pk=g["io"])
    assert g["ammesso"] is False and "altri" not in g and pg.utente is None
    # chi aspetta non riceve nulla degli altri e non può mandare segnali né stati
    Partecipante.objects.filter(pk=pa.pk).update(mano=True)
    chiamate.segnala(c, "stato", da=pa, **chiamate.descrivi(pa))
    assert _flusso(ospite, c, pg, g["dopo"]) == [] and _flusso(ospite, c, pg) == []
    assert ospite.post(reverse("discuss:chiamata_segnale", args=[c.token]), json.dumps({"a": pa.pk, "tipo": "offerta"}), content_type="application/json", headers={"X-Segreto": pg.segreto}).status_code == 403
    # il collega lo vede bussare; un ospite non può ammettere un altro ospite
    assert any(s["tipo"] == "bussa" and s["nome"] == "Giulia Esterna" for s in _flusso(client, c, pa))
    assert ospite.post(reverse("discuss:chiamata_ammetti", args=[c.token]), {"id": pg.pk, "si": "1"}).status_code == 403
    client.post(reverse("discuss:chiamata_ammetti", args=[c.token]), {"id": pg.pk, "si": "1"})
    arrivato = _flusso(ospite, c, pg, g["dopo"])
    arrivato = [x for x in arrivato if x["tipo"] == "ammesso"]
    assert arrivato[0]["tipo"] == "ammesso" and arrivato[0]["altri"][0]["nome"] == "Anna"
    assert any(s["tipo"] == "entrato" and s.get("ospite") is True for s in _flusso(client, c, pa))
    # un altro ospite rifiutato è fuori
    h = Client()
    ph = Partecipante.objects.get(pk=h.post(url, {"nome": "Disturbo"}).json()["io"])
    client.post(reverse("discuss:chiamata_ammetti", args=[c.token]), {"id": ph.pk, "si": "0"})
    assert h.get(reverse("discuss:chiamata_eventi", args=[c.token]), {"s": ph.segreto}).status_code == 403
    # il link si chiude: chi arriva dopo non entra
    client.post(reverse("discuss:chiamata_ospiti", args=[c.token]), {"si": "0"})
    assert Client().post(url, {"nome": "Tardi"}).status_code == 403
    # senza colleghi la chiamata finisce, anche se resta un ospite
    client.post(reverse("discuss:chiamata_esci", args=[c.token]), headers={"X-Segreto": pa.segreto})
    c.refresh_from_db()
    Partecipante.objects.filter(pk=pg.pk).update(uscito=timezone.now())
    chiamate.chiudi_se_vuota(c)
    c.refresh_from_db()
    assert c.finita is not None


def test_limiti_e_scomparsi(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("t", Canale.PUBBLICO, anna, [bruno])
    c = chiamate.avvia(canale, anna)
    Parametro.objects.update_or_create(chiave="discuss.max_partecipanti", azienda=None, defaults={"valore": "1"})
    client.force_login(anna)
    assert client.post(reverse("discuss:chiamata_entra", args=[c.token])).status_code == 200
    altro = Client()
    altro.force_login(bruno)
    r = altro.post(reverse("discuss:chiamata_entra", args=[c.token]))
    assert r.status_code == 409 and "completo" in r.json()["errore"]
    # chi rientra da un'altra finestra non conta due volte: la vecchia esce
    Parametro.objects.filter(chiave="discuss.max_partecipanti").update(valore="2")
    assert client.post(reverse("discuss:chiamata_entra", args=[c.token])).status_code == 200
    assert chiamate.presenti(c).count() == 1
    # chi sparisce senza salutare esce dopo il tempo senza battito, e la chiamata si chiude
    Partecipante.objects.update(ultimo_visto=timezone.now() - datetime.timedelta(minutes=5))
    assert "chiuse: 1" in chiamate.pulisci()
    c.refresh_from_db()
    assert c.finita is not None and not Partecipante.objects.filter(uscito__isnull=True).exists()


def test_canale_vocale_non_squilla_e_non_scrive(persone):
    anna, bruno, _ = persone
    stanza = servizi.crea_canale("stanza", Canale.PUBBLICO, anna, [bruno], vocale=True)
    c = chiamate.avvia(stanza, anna, video=False)
    assert Evento.objects.get(tipo="chiamata").dati["squilla"] is False and not stanza.messaggi.exists() and chiamate.squilli_per(bruno) == []
    p = chiamate.entra(c, anna)
    chiamate.esci(p)
    assert not stanza.messaggi.exists() and Chiamata.objects.get().finita is not None
    assert chiamate.avvia(stanza, anna).pk != c.pk                                # la stanza si riapre


def test_canale_di_gruppo_non_squilla(persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("t", Canale.PUBBLICO, anna, [bruno])
    chiamate.avvia(canale, anna)
    assert Evento.objects.get(tipo="chiamata").dati["squilla"] is False and chiamate.squilli_per(bruno) == []


def test_credenziali_turn_a_tempo(persone):
    Parametro.objects.update_or_create(chiave="discuss.turn_url", azienda=None, defaults={"valore": "turn:t.es:3478"})
    Parametro.objects.update_or_create(chiave="discuss.turn_segreto", azienda=None, defaults={"valore": "abc"})
    server = chiamate.server_ice()
    turn = server[-1]
    assert turn["urls"] == "turn:t.es:3478" and int(turn["username"]) > timezone.now().timestamp() and len(turn["credential"]) == 28


def test_modulo_spento_chiamate_irraggiungibili(client, persone):
    anna, bruno, _ = persone
    c = chiamate.avvia(servizi.diretto([anna, bruno]), anna)
    Chiamata.objects.filter(pk=c.pk).update(ospiti_ammessi=True)
    Modulo.objects.update_or_create(slug="discuss", defaults={"nome": "Discuss", "versione_installata": "1.3.0", "stato": "installato", "disattivato": True})
    assert client.get(reverse("discuss:chiamata", args=[c.token])).status_code == 404
    assert client.post(reverse("discuss:chiamata_entra", args=[c.token]), {"nome": "x"}).status_code == 404
