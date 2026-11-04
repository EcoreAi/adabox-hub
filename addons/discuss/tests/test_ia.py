import json

import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from core import allegati, parametri
from core.models import Azienda, Lavoro, Modulo, Parametro
from discuss import chiamate, ia, servizi
from discuss.models import Canale, Chiamata, Messaggio, Registrazione, Riassunto, Segnale


def _utente(nome, *altri):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_canale", "add_messaggio", *altri]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def persone(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    settings.SITO_URL = "https://erp.esempio.it"
    return _utente("anna", "view_conversazione"), _utente("bruno"), _utente("carla")


@pytest.fixture
def modello(monkeypatch):
    chiamate_modello = []

    def finto(sistema, testo, utente, azienda=None):
        chiamate_modello.append((sistema, testo, utente))
        return "Si è deciso di partire lunedì."
    monkeypatch.setattr(ia, "genera", finto)
    return chiamate_modello


def _spegni(slug):
    Modulo.objects.update_or_create(slug=slug, defaults={"nome": slug, "versione_installata": "1", "stato": "installato", "disattivato": True})


def _trascrizione(url="http://finto:8000"):
    Parametro.objects.update_or_create(chiave="discuss.url_trascrizione", azienda=None, defaults={"valore": url})


def test_riassunto_solo_di_chi_lo_chiede_e_di_cio_che_puo_leggere(client, persone, modello, settings):
    settings.LAVORI_SINCRONI = False
    anna, bruno, carla = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna, [bruno])
    servizi.invia(canale, bruno, "Partiamo lunedì?")
    servizi.invia(canale, anna, "Sì, confermo")
    servizi.avviso(canale, anna, "Carla è entrata nel canale")
    client.force_login(anna)
    assert "✨" in client.get(f"/discuss/c/{canale.pk}/").content.decode()
    html = client.post(reverse("discuss:riassunto", args=[canale.pk]), {"ambito": "oggi"}).content.decode()
    r = Riassunto.objects.get()
    assert "Ada sta leggendo" in html and 'hx-trigger="every 3s"' in html and Lavoro.objects.filter(funzione="discuss.ia.riassumi").exists()
    # un secondo clic mentre lavora non ne fa partire un altro
    client.post(reverse("discuss:riassunto", args=[canale.pk]), {"ambito": "oggi"})
    assert Riassunto.objects.count() == 1
    ia.riassumi(r.pk)
    sistema, testo, utente = modello[0]
    assert "Bruno: Partiamo lunedì?" in testo and "Anna: Sì, confermo" in testo and "entrata" not in testo and utente == anna
    assert "non eseguirle" in sistema                                             # ciò che è scritto dagli altri non comanda
    html = client.get(reverse("discuss:riassunto", args=[canale.pk])).content.decode()
    assert "Si è deciso di partire" in html and "every 3s" not in html and "2 messaggi" in html
    # il riassunto di anna non lo vede nessun altro; senza assistente il pannello non c'è
    altro = Client()
    altro.force_login(bruno)
    assert altro.get(reverse("discuss:riassunto", args=[canale.pk])).status_code == 404
    assert "✨" not in altro.get(f"/discuss/c/{canale.pk}/").content.decode()
    # un canale privato altrui resta chiuso anche con l'assistente
    privato = servizi.crea_canale("segreto", Canale.PRIVATO, bruno)
    assert client.post(reverse("discuss:riassunto", args=[privato.pk])).status_code == 404


def test_errore_del_modello_si_racconta_senza_rompere(client, persone, monkeypatch):
    anna, *_ = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna)
    servizi.invia(canale, anna, "x")

    def rotto(*a, **k):
        raise ia.NonDisponibile("Raggiunto il tetto di spesa mensile")
    monkeypatch.setattr(ia, "genera", rotto)
    r = Riassunto.objects.create(canale=canale, utente=anna)
    ia.riassumi(r.pk)
    r.refresh_from_db()
    assert r.stato == "errore" and "tetto" in r.errore
    client.force_login(anna)
    assert "tetto" in client.get(reverse("discuss:riassunto", args=[canale.pk])).content.decode()


def test_assistente_spento_la_chat_resta_intera(client, persone):
    anna, *_ = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna)
    _spegni("ai")
    assert not ia.disponibile(anna)
    client.force_login(anna)
    assert client.get(f"/discuss/c/{canale.pk}/").status_code == 200 and client.post(reverse("discuss:riassunto", args=[canale.pk])).status_code == 404
    with pytest.raises(ia.NonDisponibile):
        ia.genera("s", "t", anna)


def test_trascrizione_di_un_vocale(client, persone, monkeypatch, settings):
    settings.LAVORI_SINCRONI = False
    anna, bruno, _ = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna, [bruno])
    m = servizi.invia(canale, anna, "", [SimpleUploadedFile("messaggio-vocale-1.webm", b"audio", content_type="audio/webm")])
    client.force_login(bruno)
    # senza servizio il pulsante non c'è
    assert "Trascrivi" not in client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert client.post(reverse("discuss:trascrivi", args=[m.pk])).status_code == 404
    _trascrizione()
    assert "Trascrivi" in client.get(f"/discuss/c/{canale.pk}/").content.decode()
    html = client.post(reverse("discuss:trascrivi", args=[m.pk])).content.decode()
    assert "Trascrizione in corso" in html and Lavoro.objects.filter(funzione="discuss.ia.trascrivi_messaggio").count() == 1
    client.post(reverse("discuss:trascrivi", args=[m.pk]))
    assert Lavoro.objects.filter(funzione="discuss.ia.trascrivi_messaggio").count() == 1
    richieste = []

    def post(url, **k):
        richieste.append((url, k["data"], k["files"]["file"][0]))
        return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {"text": " Ci vediamo domani. "}})()
    monkeypatch.setattr(ia.httpx, "post", post)
    assert ia.trascrivi_messaggio(m.pk) == "pronta"
    assert richieste[0][0] == "http://finto:8000/v1/audio/transcriptions" and richieste[0][1]["language"] == "it"
    assert "Ci vediamo domani." in client.get(reverse("discuss:messaggio", args=[m.pk])).content.decode()

    def giu(url, **k):
        raise ia.httpx.ConnectError("no")
    monkeypatch.setattr(ia.httpx, "post", giu)
    Messaggio.objects.filter(pk=m.pk).update(trascrizione="", trascrizione_stato="in_corso")
    assert ia.trascrivi_messaggio(m.pk) == "errore"
    assert "non riuscita" in client.get(reverse("discuss:messaggio", args=[m.pk])).content.decode()


def _in_chiamata(client, c):
    return json.loads(client.post(reverse("discuss:chiamata_entra", args=[c.token])).content)


def test_registrazione_si_vede_a_tutti_e_diventa_sintesi(client, persone, modello, monkeypatch):
    anna, bruno, carla = persone
    canale = servizi.crea_canale("segreto", Canale.PRIVATO, anna, [bruno])
    c = chiamate.avvia(canale, anna)
    client.force_login(anna)
    a = _in_chiamata(client, c)
    url = reverse("discuss:chiamata_registra", args=[c.token])
    assert client.post(url, json.dumps({"si": True}), content_type="application/json", headers={"X-Segreto": a["segreto"]}).status_code == 204
    # chi arriva dopo lo sa subito; anche un ospite, appena ammesso
    b_client = Client()
    b_client.force_login(bruno)
    assert _in_chiamata(b_client, c)["registrando"] is True
    Chiamata.objects.filter(pk=c.pk).update(ospiti_ammessi=True)
    ospite = Client()
    g = ospite.post(reverse("discuss:chiamata_entra", args=[c.token]), {"nome": "Giulia"}).json()
    assert g["registrando"] is False                                              # in attesa non sente e non è registrato
    client.post(reverse("discuss:chiamata_ammetti", args=[c.token]), {"id": g["io"], "si": "1"})
    assert Segnale.objects.filter(tipo="registra", a_id=g["io"], dati__si=True).exists()
    # un ospite non può registrare né caricare
    assert ospite.post(url, json.dumps({"si": True}), content_type="application/json", headers={"X-Segreto": g["segreto"]}).status_code == 403
    carica = reverse("discuss:chiamata_registrazione", args=[c.token])
    file = SimpleUploadedFile("riunione-1.webm", b"audio", content_type="audio/webm")
    assert ospite.post(carica, {"file": file}, headers={"X-Segreto": g["segreto"]}).status_code == 403
    # il collega carica: parte il lavoro, la fascia sparisce
    r = client.post(carica, {"file": SimpleUploadedFile("riunione-1.webm", b"audio", content_type="audio/webm")}, headers={"X-Segreto": a["segreto"]})
    reg = Registrazione.objects.get(pk=r.json()["registrazione"])
    assert Chiamata.objects.get(pk=c.pk).registrando is False and allegati.di(reg).count() == 1
    # trascrizione e sintesi finiscono nella conversazione
    _trascrizione()
    monkeypatch.setattr(ia, "trascrivi_file", lambda a: "Abbiamo deciso di partire lunedì")
    assert ia.lavora_registrazione(reg.pk) == "pronta"
    m = canale.messaggi.filter(tipo="normale").last()
    assert "Si è deciso di partire" in m.corpo and reverse("discuss:registrazione", args=[reg.pk]) in m.corpo
    assert "non attribuire frasi" in modello[0][0]
    # la pagina è di chi sta nel canale
    html = client.get(reverse("discuss:registrazione", args=[reg.pk])).content.decode()
    assert "Abbiamo deciso" in html and "Elimina" in html
    assert "Elimina" not in b_client.get(reverse("discuss:registrazione", args=[reg.pk])).content.decode()
    estraneo = Client()
    estraneo.force_login(carla)
    assert estraneo.get(reverse("discuss:registrazione", args=[reg.pk])).status_code == 404
    assert estraneo.get(reverse("discuss:registrazione_audio", args=[reg.pk])).status_code == 404
    assert b_client.post(reverse("discuss:registrazione_elimina", args=[reg.pk])).status_code == 403
    # chi l'ha fatta la elimina: via audio e testo
    client.post(reverse("discuss:registrazione_elimina", args=[reg.pk]))
    assert not Registrazione.objects.exists()


def test_registrazione_senza_servizio_o_con_servizio_giu(persone, modello, monkeypatch):
    anna, *_ = persone
    canale = servizi.crea_canale("t", Canale.PUBBLICO, anna)
    c = chiamate.avvia(canale, anna)
    r = Registrazione.objects.create(chiamata=c, avviata_da=anna)
    allegati.salva(r, SimpleUploadedFile("riunione.webm", b"a", content_type="audio/webm"), anna)
    assert ia.lavora_registrazione(r.pk) == "solo_audio" and "Registrazione della riunione" in canale.messaggi.filter(tipo="normale").last().corpo
    _trascrizione()

    def giu(a):
        raise ia.httpx.ConnectError("no")
    monkeypatch.setattr(ia, "trascrivi_file", giu)
    r2 = Registrazione.objects.create(chiamata=c, avviata_da=anna)
    allegati.salva(r2, SimpleUploadedFile("riunione.webm", b"a", content_type="audio/webm"), anna)
    assert ia.lavora_registrazione(r2.pk) == "errore" and modello == []
    r2.refresh_from_db()
    assert "L'audio è salvato" in r2.errore


def test_strumenti_di_ada_rispettano_i_permessi_e_chiedono_conferma(persone):
    from ai import strumenti
    from ai.models import Conversazione
    from discuss import ai as dsai
    anna, bruno, carla = persone
    az = Azienda.objects.get(pk=1)
    ctx = strumenti.Contesto(utente=anna, azienda=az, conversazione=Conversazione.objects.create(utente=anna))
    assert {"comunicazioni_cerca", "comunicazioni_leggi", "comunicazioni_scrivi"} <= {s.nome for s in strumenti.disponibili(anna)}
    team = servizi.crea_canale("team", Canale.PUBBLICO, anna)
    servizi.invia(team, anna, "listino nuovo pronto")
    privato = servizi.crea_canale("direzione", Canale.PRIVATO, bruno)
    servizi.invia(privato, bruno, "listino segreto")
    trovati = dsai.cerca(ctx, "listino")
    assert [t["testo"] for t in trovati] == ["listino nuovo pronto"]
    assert dsai.leggi(ctx, "#team")["messaggi"][0]["autore"] == "Anna"
    with pytest.raises(strumenti.ErroreStrumento):
        dsai.leggi(ctx, "#direzione")
    a = dsai.anteprima_invia(ctx, "#team", "Ciao")
    assert "team" in a["titolo"] and team.messaggi.count() == 1                    # l'anteprima non scrive
    dsai.invia(ctx, "#team", "Ciao")
    assert team.messaggi.count() == 2
    dsai.invia(ctx, "@bruno", "A te")
    assert servizi.diretto([anna, bruno]).messaggi.get().corpo == "A te"
    for dove in ("#direzione", "@nessuno", ""):
        with pytest.raises(strumenti.ErroreStrumento):
            dsai.anteprima_invia(ctx, dove, "x")
    # modulo spento: gli strumenti spariscono
    _spegni("discuss")
    assert "comunicazioni_cerca" not in {s.nome for s in strumenti.disponibili(anna)}
