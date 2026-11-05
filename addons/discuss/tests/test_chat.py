import datetime
import json

import httpx2 as httpx
import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core import rete
from core.models import Messaggio as MessaggioChatter
from discuss import anteprime, eventi, notifiche, presenza, servizi, testo
from discuss.models import Canale, Evento, Iscrizione, Messaggio, Notifica, Presenza, Reazione


def _utente(nome):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="discuss",
                                                     codename__in=["view_canale", "add_canale", "add_messaggio"]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def persone(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    return _utente("anna"), _utente("bruno"), _utente("carla")


def _eventi(risposta):
    testo_sse = b"".join(risposta.streaming_content).decode()
    return [json.loads(riga[6:]) for riga in testo_sse.splitlines() if riga.startswith("data: ")], testo_sse


def test_forme_del_testo_senza_falsi_canali(persone):
    Canale.objects.create(nome="commerciale", tipo=Canale.PUBBLICO)
    html = testo.rendi("*corsivo* ~~via~~ `**non grassetto**` #commerciale #inesistente l'apostrofo")
    assert "<em>corsivo</em>" in html and "<del>via</del>" in html and "<code>**non grassetto**</code>" in html
    assert 'href="/discuss/vai/commerciale/">#commerciale</a>' in html and "#inesistente" in html and "vai/inesistente" not in html
    assert "x27</a>" not in html and "&#x27;" in html                          # l'escape dell'apostrofo non è un canale
    assert testo.rendi("```\n<b>x</b> @anna\n```").count("<pre>") == 1 and "ds-menzione" not in testo.rendi("```@anna```")
    assert "<mark>Ciao</mark>" in testo.evidenzia("Ciao mondo", "ciao da:anna")


def test_reazioni_risposte_e_fissati(client, persone):
    anna, bruno, carla = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna, [bruno])
    m = servizi.invia(canale, anna, "Domanda")
    client.force_login(bruno)
    html = client.post(f"/discuss/m/{m.pk}/reazione/", {"emoji": "👍"}).content.decode()
    assert "ds-reazione is-mia" in html and Reazione.objects.count() == 1
    client.post(f"/discuss/m/{m.pk}/reazione/", {"emoji": "👍"})
    assert Reazione.objects.count() == 0
    assert client.post(f"/discuss/m/{m.pk}/reazione/", {"emoji": "testo"}).status_code == 422
    # risposta: citazione nel messaggio, conteggio sull'originale, pannello e notifica ad Anna
    r = client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "Risposta", "risposta_a": m.pk}, headers={"HX-Request": "true"})
    assert r.status_code == 204
    risposta = canale.messaggi.last()
    assert risposta.risposta_a == m and Notifica.objects.filter(utente=anna, tipo=Notifica.RISPOSTA).exists()
    html = client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert "ds-citato" in html and "1 risposta" in html
    assert "Risposta" in client.get(f"/discuss/m/{m.pk}/risposte/").content.decode()
    # fissato: compare nel pannello e nel contatore
    assert "is-fissato" in client.post(f"/discuss/m/{m.pk}/fissa/").content.decode()
    assert "Domanda" in client.get(f"/discuss/c/{canale.pk}/fissati/").content.decode()
    assert Evento.objects.filter(tipo="agg", dati__n_fissati=1).exists()
    # chi non è iscritto legge il canale pubblico ma non reagisce né fissa
    client.force_login(carla)
    assert client.post(f"/discuss/m/{m.pk}/reazione/", {"emoji": "👍"}).status_code == 403
    assert client.post(f"/discuss/m/{m.pk}/fissa/").status_code == 403


def test_segna_da_leggere_resta_finche_non_si_riapre(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna, [bruno])
    altro = servizi.crea_canale("altro", Canale.PUBBLICO, anna, [bruno])
    uno, due = servizi.invia(canale, anna, "uno"), servizi.invia(canale, anna, "due")
    client.force_login(bruno)
    client.get(f"/discuss/c/{canale.pk}/")
    assert servizi.totale_non_letti(bruno) == 0
    assert client.post(f"/discuss/m/{due.pk}/da-leggere/").status_code == 204
    assert servizi.totale_non_letti(bruno) == 1
    # l'aggiornamento della pagina aperta non lo azzera, e /discuss/ non riapre quella conversazione da solo
    servizi.invia(canale, anna, "tre")
    client.get(f"/discuss/c/{canale.pk}/nuovi/?dopo={due.pk}")
    assert servizi.totale_non_letti(bruno) == 2
    servizi.invia(altro, anna, "ciao")
    assert client.get("/discuss/").url == f"/discuss/c/{altro.pk}/"
    client.get(f"/discuss/c/{canale.pk}/")
    client.get(f"/discuss/c/{altro.pk}/")
    assert servizi.totale_non_letti(bruno) == 0 and uno.pk < due.pk


def test_ruoli_e_canale_gestito(client, persone):
    anna, bruno, carla = persone
    canale = servizi.crea_canale("annunci", Canale.PUBBLICO, anna, [bruno, carla], gestito=True)
    assert Iscrizione.objects.get(canale=canale, utente=anna).ruolo == Iscrizione.AMMINISTRATORE
    m = servizi.invia(canale, anna, "Avviso")
    # il membro legge ma non scrive, non fissa, non tocca le impostazioni
    client.force_login(bruno)
    html = client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert "scrivono amministratori" in html and "data-scrivi" not in html
    assert client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "x"}).status_code == 403
    assert client.post(f"/discuss/m/{m.pk}/fissa/").status_code == 403
    assert client.post(f"/discuss/m/{m.pk}/elimina/").status_code == 403
    assert client.post(f"/discuss/c/{canale.pk}/ruolo/", {"utente": bruno.pk, "ruolo": "amministratore"}).status_code == 403
    # l'amministratore nomina un contributore, che scrive, e un moderatore, che toglie i messaggi altrui
    client.force_login(anna)
    assert "ds-ruolo" in client.get(f"/discuss/c/{canale.pk}/info/").content.decode()
    client.post(f"/discuss/c/{canale.pk}/ruolo/", {"utente": bruno.pk, "ruolo": "contributore"})
    client.post(f"/discuss/c/{canale.pk}/ruolo/", {"utente": carla.pk, "ruolo": "moderatore"})
    client.force_login(bruno)
    assert client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "ok"}).status_code == 302
    client.force_login(carla)
    assert client.post(f"/discuss/m/{m.pk}/elimina/").status_code == 200
    # l'amministratore esce: il canale passa al moderatore; chi resta vede l'avviso discreto, che non è un non letto
    client.force_login(anna)
    client.post(f"/discuss/c/{canale.pk}/esci/")
    assert Iscrizione.objects.get(canale=canale, utente=carla).ruolo == Iscrizione.AMMINISTRATORE
    avviso = canale.messaggi.filter(tipo=Messaggio.SISTEMA).last()
    assert "Anna è uscito" in avviso.corpo and "ds-avviso-riga" in _pagina(client, carla, canale)
    assert servizi.iscrizioni_di(carla)[0].non_letti is None or avviso.pk <= servizi.iscrizioni_di(carla)[0].ultimo_letto
    # archiviato: niente scrittura
    client.force_login(carla)
    client.post(f"/discuss/c/{canale.pk}/impostazioni/", {"nome": "annunci", "tipo": "pubblico", "archiviato": "1"})
    assert client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "x"}).status_code == 403


def _pagina(client, utente, canale):
    client.force_login(utente)
    return client.get(f"/discuss/c/{canale.pk}/").content.decode()


def test_gruppo_da_un_messaggio_diretto(client, persone):
    anna, bruno, carla = persone
    dm = servizi.diretto([anna, bruno])
    servizi.invia(dm, anna, "privato")
    client.force_login(anna)
    r = client.post(f"/discuss/c/{dm.pk}/gruppo/", {"utenti": [carla.pk], "nome": "Fiera"})
    gruppo = Canale.objects.get(nome="Fiera")
    assert r.url == f"/discuss/c/{gruppo.pk}/" and gruppo.pk != dm.pk and gruppo.diretto and gruppo.membri.count() == 3
    assert gruppo.titolo_per(anna) == "Fiera" and not dm.iscrizioni.filter(utente=carla).exists()   # lo storico a due resta a due
    assert not gruppo.messaggi.filter(corpo="privato").exists()
    assert client.post(f"/discuss/c/{servizi.crea_canale('x', Canale.PUBBLICO, anna).pk}/gruppo/", {"utenti": [carla.pk]}).status_code == 403


def test_presenza_e_fuori_ufficio(client, persone):
    anna, bruno, _ = persone
    assert presenza.scheda(None)["stato"] == presenza.OFFLINE
    client.force_login(bruno)
    client.get("/discuss/contatore/?attivo=1")
    p = Presenza.objects.get(utente=bruno)
    assert presenza.stato_da(p) == presenza.ONLINE
    ora = timezone.now()
    p.ultima_attivita = ora - datetime.timedelta(minutes=20)
    assert presenza.stato_da(p) == presenza.ASSENTE
    p.stato = Presenza.OCCUPATO
    assert presenza.stato_da(p) == presenza.OCCUPATO
    p.ultimo_visto = ora - datetime.timedelta(minutes=5)
    assert presenza.stato_da(p) == presenza.OFFLINE
    # lo stato scelto: chi scrive vede fino a quando è via e il messaggio
    domani = timezone.localdate() + datetime.timedelta(days=3)
    client.post("/discuss/presenza/", {"stato": "auto", "messaggio": "In ferie", "fuori_fino": domani.isoformat(), "torna": "https://altrove.it/"})
    p.refresh_from_db()
    assert p.fuori_fino == domani and presenza.stato_da(p) == presenza.FUORI
    dm = servizi.diretto([anna, bruno])
    html = _pagina(client, anna, dm)
    assert "Fuori ufficio fino al" in html and "In ferie" in html and "ds-fascia" in html
    # scaduta la data torna normale
    Presenza.objects.filter(utente=bruno).update(fuori_fino=timezone.localdate() - datetime.timedelta(days=1))
    assert presenza.stato_da(Presenza.objects.get(utente=bruno)) != presenza.FUORI


def test_ricerca_rispetta_i_permessi_e_capisce_i_filtri(client, persone):
    anna, bruno, carla = persone
    pubblico = servizi.crea_canale("vendite", Canale.PUBBLICO, anna)
    privato = servizi.crea_canale("segreto", Canale.PRIVATO, anna, [bruno])
    dm = servizi.diretto([anna, bruno])
    m1 = servizi.invia(pubblico, anna, "preventivo Rossi")
    m2 = servizi.invia(privato, bruno, "preventivo segreto")
    m3 = servizi.invia(dm, bruno, "preventivo privato")
    servizi.invia(pubblico, bruno, "altro", [SimpleUploadedFile("a.txt", b"x")])
    assert [m.pk for m in servizi.cerca(carla, "preventivo")] == [m1.pk]
    assert {m.pk for m in servizi.cerca(bruno, "preventivo")} == {m1.pk, m2.pk, m3.pk}
    assert [m.pk for m in servizi.cerca(anna, "preventivo da:bruno in:segreto")] == [m2.pk]
    assert [m.corpo for m in servizi.cerca(anna, "ha:file")] == ["altro"] and servizi.cerca(anna, "") == []
    client.force_login(carla)
    html = client.get("/discuss/cerca/", {"q": "preventivo"}).content.decode()
    assert "<mark>preventivo</mark>" in html and "segreto" not in html and f"?a={m1.pk}" in html
    # dal risultato alla conversazione, attorno al messaggio: lo storico non segna letto e non ha il poller
    for i in range(70):
        servizi.invia(pubblico, anna, f"m{i}")
    html = client.get(f"/discuss/c/{pubblico.pk}/?a={m1.pk}").content.decode()
    assert "preventivo Rossi" in html and "Torna agli ultimi" in html and 'id="ds-poller"' not in html


def test_suggerimenti_palette_e_menzioni_cliccabili(client, persone):
    anna, bruno, carla = persone
    servizi.crea_canale("vendite", Canale.PUBBLICO, anna)
    servizi.crea_canale("vendite-segreto", Canale.PRIVATO, anna)
    client.force_login(bruno)
    assert [v["valore"] for v in client.get("/discuss/suggerisci/", {"q": "car"}).json()["voci"]] == ["carla"]
    assert [v["valore"] for v in client.get("/discuss/suggerisci/", {"q": "vend", "tipo": "canali"}).json()["voci"]] == ["vendite"]
    voci = client.get("/discuss/palette/", {"q": "vend"}).json()["voci"]
    assert voci[0]["testo"] == "vendite" and voci[-1]["tipo"] == "cerca" and not any("segreto" in v["testo"] for v in voci)
    # il clic sulla menzione apre il diretto (sempre lo stesso); un nome inesistente torna a casa con un messaggio
    r = client.get("/discuss/con/carla/")
    assert r.status_code == 302 and client.get("/discuss/con/carla/").url == r.url and Canale.objects.filter(tipo="diretto").count() == 1
    assert client.get("/discuss/con/nessuno/").status_code == 302 and Canale.objects.filter(tipo="diretto").count() == 1
    assert client.get("/discuss/vai/vendite/").url.startswith("/discuss/c/")
    assert client.get("/discuss/vai/vendite-segreto/").url == "/discuss/"
    # senza permesso la palette è vuota
    senza = User.objects.create_user("senza", password="x")
    client.force_login(senza)
    assert client.get("/discuss/palette/", {"q": "vend"}).json() == {"voci": []}


def test_eventi_in_tempo_reale_solo_a_chi_tocca(client, persone):
    anna, bruno, carla = persone
    privato = servizi.crea_canale("segreto", Canale.PRIVATO, anna, [bruno])
    pubblico = servizi.crea_canale("vendite", Canale.PUBBLICO, anna)
    inizio = eventi.ultimo_id()
    servizi.invia(privato, anna, "x")
    servizi.invia(pubblico, anna, "y")
    client.force_login(bruno)
    r = client.get("/discuss/eventi/", {"dopo": inizio})
    assert r["Content-Type"].startswith("text/event-stream") and r["X-Accel-Buffering"] == "no"
    dati, grezzo = _eventi(r)
    assert "retry: 3000" in grezzo and {d["canale"] for d in dati if d["tipo"] == "nuovo"} == {privato.pk}
    # il pubblico che si sta guardando si riceve senza esserci iscritti, il privato altrui no
    client.force_login(carla)
    dati, _ = _eventi(client.get("/discuss/eventi/", {"dopo": inizio, "canale": pubblico.pk}))
    assert {d["canale"] for d in dati if d["tipo"] == "nuovo"} == {pubblico.pk}
    dati, _ = _eventi(client.get("/discuss/eventi/", {"dopo": inizio, "canale": privato.pk}))
    assert not [d for d in dati if d["canale"] == privato.pk]
    # ripresa dopo una caduta e senza permesso
    dati, _ = _eventi(client.get("/discuss/eventi/", HTTP_LAST_EVENT_ID=str(eventi.ultimo_id())))
    assert dati == []
    client.force_login(User.objects.create_user("senza", password="x"))
    assert client.get("/discuss/eventi/").status_code == 403
    # gli eventi vecchi si buttano
    Evento.objects.update(creato=timezone.now() - datetime.timedelta(days=2))
    assert eventi.pulisci().startswith("eventi eliminati") and not Evento.objects.exists()
    # e chi scrive lo fa sapere agli altri
    client.force_login(anna)
    assert client.post(f"/discuss/c/{pubblico.pk}/scrivo/").status_code == 204
    assert Evento.objects.get(tipo="scrive").dati["nome"] == "Anna"


def test_file_immagini_e_vocali(client, persone):
    anna, bruno, _ = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna, [bruno])
    client.force_login(anna)
    client.post(f"/discuss/c/{canale.pk}/invia/", {"corpo": "", "file": [SimpleUploadedFile("messaggio-vocale-1.webm", b"voce"),
                                                                        SimpleUploadedFile("foto.png", b"img"),
                                                                        SimpleUploadedFile("doc.pdf", b"pdf")]})
    html = client.get(f"/discuss/c/{canale.pk}/").content.decode()
    assert "<audio" in html and "<img" in html and "doc.pdf" in html
    assert "doc.pdf" in client.get(f"/discuss/c/{canale.pk}/file/").content.decode()


def _client_finto(risposte):
    def gestore(request):
        risposte["viste"].append((str(request.url), request.headers.get("host")))
        return risposte["fn"](request)
    return httpx.Client(transport=httpx.MockTransport(gestore), follow_redirects=False)


def test_anteprime_dei_link_e_protezione_della_rete_interna(persone, monkeypatch, settings):
    anna, *_ = persone
    canale = servizi.crea_canale("team", Canale.PUBBLICO, anna)
    risposte = {"viste": [], "fn": lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=(
        '<title>Vecchio</title><meta property="og:title" content="Offerta &amp; prezzi"><meta name="description" content="Tutti i dettagli">'))}
    client = _client_finto(risposte)
    # un nome pubblico: la connessione va all'indirizzo controllato, con il nome nell'intestazione
    monkeypatch.setattr(rete.socket, "getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", ("93.184.216.34", p))])
    m = servizi.invia(canale, anna, "guarda https://esempio.it/a?x=1")
    anteprime.calcola(m.pk, http_client=client)
    m.refresh_from_db()
    assert m.anteprime == [{"url": "https://esempio.it/a?x=1", "titolo": "Offerta & prezzi", "descrizione": "Tutti i dettagli", "sito": "esempio.it"}]
    assert risposte["viste"][0] == ("https://93.184.216.34/a?x=1", "esempio.it")
    assert Evento.objects.filter(tipo="agg", dati__m=m.pk).exists()
    # indirizzi interni, porte strane e credenziali: non si contatta niente
    risposte["viste"].clear()
    for indirizzo in ("127.0.0.1", "10.0.0.8", "169.254.169.254", "192.168.1.1", "::1", "fd00::1"):
        monkeypatch.setattr(rete.socket, "getaddrinfo", lambda h, p, ip=indirizzo, **k: [(2, 1, 6, "", (ip, p))])
        n = servizi.invia(canale, anna, "http://interno.it/admin")
        anteprime.calcola(n.pk, http_client=client)
        assert Messaggio.objects.get(pk=n.pk).anteprime == []
    for url in ("http://esempio.it:8080/", "http://u:p@esempio.it/", "ftp://esempio.it/"):
        with pytest.raises(anteprime.Rifiutato):
            anteprime._controlla(url)
    assert risposte["viste"] == []
    # un reindirizzamento verso la rete interna si ferma al controllo
    def indirizzo(h, p, **k):
        return [(2, 1, 6, "", ("10.0.0.8" if h == "interno.it" else "93.184.216.34", p))]
    monkeypatch.setattr(rete.socket, "getaddrinfo", indirizzo)
    risposte["fn"] = lambda r: httpx.Response(302, headers={"location": "http://interno.it/segreti"})
    n = servizi.invia(canale, anna, "https://esempio.it/vai")
    anteprime.calcola(n.pk, http_client=client)
    assert Messaggio.objects.get(pk=n.pk).anteprime == [] and len(risposte["viste"]) == 1
    # i link allo stesso gestionale non si scaricano
    settings.SITO_URL = "https://erp.esempio.it"
    risposte["viste"].clear()
    n = servizi.invia(canale, anna, "https://erp.esempio.it/crm/1/")
    anteprime.calcola(n.pk, http_client=client)
    assert risposte["viste"] == []


def test_modulo_spento_non_accumula_e_sparisce(client, persone, superuser):
    from core.models import Modulo
    from todo.models import Attivita
    from core import chatter
    from core.models import Azienda
    anna, bruno, _ = persone
    bruno.user_permissions.add(Permission.objects.get(codename="view_attivita"))
    record = Attivita.objects.create(azienda=Azienda.objects.get(pk=1), titolo="X")
    chatter.scrivi(record, anna, "@bruno guarda", tipo=MessaggioChatter.NOTA)
    assert Notifica.objects.filter(utente=bruno).count() == 1
    client.force_login(bruno)
    assert "discuss/palette.js" in client.get("/").content.decode() or "discuss/palette.js" in client.get("/dashboard/").content.decode()
    Modulo.objects.update_or_create(slug="discuss", defaults={"nome": "Discuss", "versione_installata": "1.1.0", "stato": "installato", "disattivato": True})
    chatter.scrivi(record, anna, "@bruno ancora", tipo=MessaggioChatter.NOTA)
    assert Notifica.objects.filter(utente=bruno).count() == 1
    assert client.get("/discuss/").status_code == 404 and client.get("/discuss/eventi/").status_code == 404
    html = client.get("/dashboard/", follow=True).content.decode()
    assert "discuss/palette.js" not in html and "ds-campanella" not in html
    assert notifiche.non_lette(bruno) == 1


def test_ada_non_consegna_in_un_modulo_spento(persone):
    from ai import pianificate
    from core.models import Modulo
    assert pianificate.discuss_attivo()
    Modulo.objects.update_or_create(slug="discuss", defaults={"nome": "Discuss", "versione_installata": "1.1.0", "stato": "installato", "disattivato": True})
    assert not pianificate.discuss_attivo()


def test_anteprime_su_una_riga_senza_segni():
    assert testo.piano("**forte** e `codice`\n*corsivo* ~~via~~") == "forte e codice corsivo via"
