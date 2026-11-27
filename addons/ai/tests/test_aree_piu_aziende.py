"""Chi lavora in più aziende: la colonna delle aree le mostra tutte, raggruppate per azienda (la corrente per prima), e
ogni link a una chat o a un'area di un'altra sua azienda porta data-cambia-azienda (il clic cambia azienda e la apre).
Aperta con un GET diretto risponde «Passa a …»; scriverci con un'altra azienda corrente (una scheda rimasta aperta) è
rifiutato, così Ada non risponde con i dati dell'azienda sbagliata. Chi ha una sola azienda vede la chat di prima."""
import json
from html import unescape

import pytest
from django.contrib.auth.models import Permission, User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from ai import aree, documenti_chat, pagine, parla
from ai.models import Apertura, AreaCorrente, Conversazione, MessaggioChat, ProgettoChat, Turno
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)
from core.models import Azienda


def _utente(nome, *aziende):
    u = User.objects.create_user(nome, password="x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.profilo.aziende.set(aziende)
    u.profilo.azienda_predefinita = aziende[0]
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def p(s, client):
    """Anna lavora in Rossi (corrente), Bianchi e Verdi: un'area e una chat in Rossi e in Bianchi."""
    rossi, bianchi = s["az"], s["altra"]
    rossi.nome, bianchi.nome = "Rossi Srl", "Bianchi Spa"
    rossi.save(update_fields=["nome"])
    bianchi.save(update_fields=["nome"])
    verdi = Azienda.objects.create(nome="Verdi Snc")
    u = s["u"]
    u.profilo.aziende.set([rossi, bianchi, verdi])
    area_r = ProgettoChat.objects.create(utente=u, azienda=rossi, nome="Commessa Alfa")
    area_b = ProgettoChat.objects.create(utente=u, azienda=bianchi, nome="Commessa Beta")
    chat_r = Conversazione.objects.create(utente=u, titolo="Chat di Rossi", progetto=area_r, preferita=True)
    chat_b = Conversazione.objects.create(utente=u, titolo="Chat di Bianchi", progetto=area_b, preferita=True)
    client.force_login(User.objects.get(pk=u.pk))
    return {**s, "rossi": rossi, "bianchi": bianchi, "verdi": verdi, "area_r": area_r, "area_b": area_b,
            "chat_r": chat_r, "chat_b": chat_b}


def _pannello(html, chiave):
    return html.split(f'data-contenuto="{chiave}"')[1].split("</section>")[0]


def _form_passa(html):
    """Il form del bottone «Passa a …» della pagina (non quello nascosto dell'header): un POST a core:cambia_azienda."""
    form = html.split('class="ui-card-body"')[1].split("</form>")[0]
    assert f'<form method="post" action="{reverse("core:cambia_azienda")}"' in form
    return form


def _link(html, url):
    """Il tag <a …> del link a `url`."""
    return html.split(f'href="{url}"')[1].split(">")[0]


# --- colonna delle aree ---

def test_colonna_delle_aree_raggruppata_per_azienda(client, p):
    personale_b = aree.personale(p["u"], p["bianchi"])                  # in Bianchi c'è già, in Verdi non ancora
    html = unescape(client.get(reverse("ai:chat")).content.decode())
    assert "data-cambia-azienda-form" in html                          # il form del cambio (header del kernel)
    pannello = _pannello(html, "progetti")
    gruppi = pannello.split('class="ai-gruppo-azienda"')[1:]
    assert [g.split("</summary>")[0].split("<span>")[1].split("</span>")[0] for g in gruppi] == ["Rossi Srl", "Bianchi Spa", "Verdi Snc"]
    assert gruppi[0].split(">")[0].endswith(" open") and all(" open" not in g.split(">")[0] for g in gruppi[1:])
    url_r, url_b = reverse("ai:progetto", args=[p["area_r"].pk]), reverse("ai:progetto", args=[p["area_b"].pk])
    assert url_r in gruppi[0] and "data-cambia-azienda" not in _link(gruppi[0], url_r)
    assert url_b in gruppi[1] and f'data-cambia-azienda="{p["bianchi"].pk}"' in _link(gruppi[1], url_b)
    assert f'data-cambia-azienda="{p["bianchi"].pk}"' in _link(gruppi[1], reverse("ai:progetto", args=[personale_b.pk]))
    assert gruppi[0].count("Il mio spazio") == 1 and gruppi[1].count("Il mio spazio") == 1 and "Il mio spazio" not in gruppi[2]
    # senza area personale (in Verdi non ha ancora scritto): «Nuova chat» ci passa, e la chat la crea lì
    assert f'data-cambia-azienda="{p["verdi"].pk}"' in _link(gruppi[2], reverse("ai:chat"))
    assert reverse("ai:chat") not in gruppi[1]
    assert "Commessa Beta" not in gruppi[0] and "Commessa Alfa" not in gruppi[1]   # ogni area nella sua azienda


def test_un_get_non_crea_aree_nelle_altre_aziende(client, p):
    client.get(reverse("ai:chat"))
    client.get(reverse("ai:conversazione", args=[p["chat_r"].pk]))
    assert list(ProgettoChat.objects.filter(azienda=p["bianchi"])) == [p["area_b"]]
    assert not ProgettoChat.objects.filter(azienda=p["verdi"]).exists()
    assert ProgettoChat.objects.filter(azienda=p["rossi"], personale=True).exists()   # nella corrente sì, come prima


def _query(client, url):
    with CaptureQueriesContext(connection) as q:
        assert client.get(url).status_code == 200
    return len(q.captured_queries)


def test_query_delle_altre_aziende(client, s, p, monkeypatch):
    """Le aree delle altre aziende costano al più due query (aziende, aree), quante che siano le aziende; per chi ha
    una sola azienda nessuna."""
    url = reverse("ai:chat")
    _query(client, url)
    con = _query(client, url)
    monkeypatch.setattr(pagine, "_aree_delle_altre_aziende", lambda request: [])
    senza = _query(client, url)
    assert con - senza <= 2
    monkeypatch.undo()
    p["u"].profilo.aziende.set([p["rossi"]])                             # una sola azienda
    _query(client, url)
    con = _query(client, url)
    monkeypatch.setattr(pagine, "_aree_delle_altre_aziende", lambda request: pytest.fail("calcolate con una sola azienda"))
    monkeypatch.setattr(aree, "consentite", lambda user: pytest.fail("consentite chiesta di nuovo con una sola azienda"))
    assert _query(client, url) == con


# --- l'app Chat riservata ad alcune aziende (Modulo.aziende) ---

@pytest.fixture
def solo_rossi(p, client):
    """La Chat c'è solo in Rossi: passare a Bianchi o Verdi porterebbe a una chat che risponde 403."""
    from core.models import Modulo
    modulo, _ = Modulo.objects.get_or_create(slug="ai")
    modulo.aziende.set([p["rossi"]])
    client.force_login(User.objects.get(pk=p["u"].pk))
    return p


def test_chat_riservata_niente_gruppi_ne_cambio_verso_aziende_senza_chat(client, solo_rossi):
    p = solo_rossi
    html = unescape(client.get(reverse("ai:chat")).content.decode())
    assert "ai-gruppo-azienda" not in html and reverse("ai:progetto", args=[p["area_b"].pk]) not in html
    assert not ProgettoChat.objects.filter(azienda__in=[p["bianchi"], p["verdi"]], personale=True).exists()
    url_b = reverse("ai:conversazione", args=[p["chat_b"].pk])
    for elenco in (_pannello(html, "storico"), _pannello(html, "preferite")):
        voce_b = elenco.split("Chat di Bianchi")[0].rsplit("<li>", 1)[1]
        assert 'class="ai-elenco-azienda">Bianchi Spa<' in elenco and f'href="{url_b}"' not in voce_b   # il nome, senza link
        assert "data-cambia-azienda" not in voce_b
    assert client.get(url_b).status_code == 404
    assert client.get(reverse("ai:progetto", args=[p["area_b"].pk])).status_code == 404
    assert client.get(reverse("ai:parla_conversazione", args=[p["chat_b"].pk])).status_code == 404
    r = client.post(reverse("ai:invia_conversazione", args=[p["chat_b"].pk]), {"testo": "ciao"}, HTTP_HX_REQUEST="true")
    motivo = json.loads(r.headers["HX-Trigger"])["ai-errore"]
    assert "passa a" not in motivo and "apri una chat nuova" in motivo and not Turno.objects.exists()


def test_con_una_sola_azienda_la_chat_di_prima(client, s):
    area = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Commessa Alfa")
    chat = Conversazione.objects.create(utente=s["u"], titolo="Chat sola", progetto=area, preferita=True)
    for url in (reverse("ai:chat"), reverse("ai:conversazione", args=[chat.pk]), reverse("ai:progetto", args=[area.pk])):
        html = client.get(url).content.decode()
        for nuovo in ("ai-gruppo-azienda", "data-cambia-azienda", "ai-elenco-azienda", "ai-area-azienda"):
            assert nuovo not in html, (url, nuovo)
    assert "ai-gruppo-azienda" not in client.get(reverse("ai:cerca_chat"), {"q": "sola"}).content.decode()


# --- apertura diretta con GET ---

def test_get_diretto_di_una_chat_di_un_altra_azienda_propone_di_passarci(client, p):
    url = reverse("ai:conversazione", args=[p["chat_b"].pk]) + "?scritta=1"
    r = client.get(url)
    html = unescape(r.content.decode())
    assert r.status_code == 403 and "Questa chat è dell'azienda Bianchi Spa" in html
    form = _form_passa(html)
    assert f'name="azienda" value="{p["bianchi"].pk}"' in form and f'name="next" value="{url}"' in form and "Passa a Bianchi Spa" in form
    assert r.wsgi_request.azienda == p["rossi"]                         # il GET non cambia azienda
    r = client.post(reverse("core:cambia_azienda"), {"azienda": p["bianchi"].pk, "next": url})
    assert r.status_code == 302 and r.url == url
    r = client.get(url)
    assert r.status_code == 200 and r.wsgi_request.azienda == p["bianchi"] and "Chat di Bianchi" in r.content.decode()


def test_get_diretto_di_un_area_di_un_altra_azienda_propone_di_passarci(client, p):
    url = reverse("ai:progetto", args=[p["area_b"].pk])
    r = client.get(url)
    html = unescape(r.content.decode())
    assert r.status_code == 403 and "L'area «Commessa Beta» è dell'azienda Bianchi Spa" in html
    form = _form_passa(html)
    assert f'name="azienda" value="{p["bianchi"].pk}"' in form and f'name="next" value="{url}"' in form
    assert not AreaCorrente.objects.filter(utente=p["u"], azienda=p["bianchi"]).exists()    # aprirla non l'ha resa corrente
    client.post(reverse("core:cambia_azienda"), {"azienda": p["bianchi"].pk, "next": url})
    r = client.get(url)
    assert r.status_code == 200 and "Commessa Beta" in r.content.decode() and aree.corrente(p["u"], p["bianchi"]) == p["area_b"]


def test_get_diretto_di_una_chat_condivisa_di_un_altra_azienda(client, p):
    bruno = _utente("bruno", p["bianchi"])
    area = ProgettoChat.objects.create(utente=bruno, azienda=p["bianchi"], nome="Di Bruno")
    aree.imposta_membri(area, [p["u"]])
    sua = Conversazione.objects.create(utente=bruno, titolo="Analisi di Bruno", progetto=area, condivisa=True)
    r = client.get(reverse("ai:conversazione", args=[sua.pk]))
    assert r.status_code == 403 and "Questa chat è dell'azienda Bianchi Spa" in unescape(r.content.decode())


def test_senza_quell_azienda_resta_404(client, p):
    carla = _utente("carla", p["rossi"])
    client.force_login(carla)
    assert client.get(reverse("ai:progetto", args=[p["area_b"].pk])).status_code == 404
    assert client.get(reverse("ai:conversazione", args=[p["chat_b"].pk])).status_code == 404
    client.force_login(p["u"])
    p["u"].profilo.aziende.set([p["rossi"]])                             # Anna non lavora più in Bianchi
    assert client.get(reverse("ai:progetto", args=[p["area_b"].pk])).status_code == 404


def test_parla_con_ada_su_una_chat_di_un_altra_azienda(client, p, monkeypatch):
    r = client.get(reverse("ai:parla_conversazione", args=[p["chat_b"].pk]))
    assert r.status_code == 403 and "Questa chat è dell'azienda Bianchi Spa" in unescape(r.content.decode())
    monkeypatch.setattr(parla, "disponibile", lambda azienda: True)
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "quante fatture", "conversazione": p["chat_b"].pk})
    assert r.status_code == 400 and r.json()["errore"] == "Questa chat è dell'azienda Bianchi Spa: passa a Bianchi Spa per continuare."
    assert not Turno.objects.exists()


def test_parla_con_ada_non_ferma_la_risposta_in_corso_in_una_chat_di_un_altra_azienda(client, p, monkeypatch):
    """Una domanda a voce interrompe la risposta a voce in corso: in una chat di un'altra azienda prima si rifiuta, e
    la risposta di là non si ferma (né si aspetta che si chiuda)."""
    monkeypatch.setattr(parla, "disponibile", lambda azienda: True)
    in_corso = Turno.objects.create(conversazione=p["chat_b"], utente=p["u"], voce=True)
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "basta così", "conversazione": p["chat_b"].pk})
    assert r.status_code == 400 and r.json()["errore"] == "Questa chat è dell'azienda Bianchi Spa: passa a Bianchi Spa per continuare."
    in_corso.refresh_from_db()
    assert in_corso.stato == Turno.IN_CORSO and not in_corso.richiesta_stop
    assert Turno.objects.count() == 1


def test_parla_con_ada_si_riprendiamo_una_chat_di_un_altra_azienda(client, p, monkeypatch):
    """«Sì, riprendiamo» dopo l'apertura di Ada: la chat da riprendere è di Bianchi, l'azienda corrente è Rossi."""
    monkeypatch.setattr(parla, "disponibile", lambda azienda: True)
    saluto = Apertura.objects.create(utente=p["u"], azienda=p["rossi"], tipo=Apertura.RIPRENDI, testo="Riprendiamo?",
                                     riferimento=str(p["chat_b"].pk), conversazione=p["chat_b"])
    r = client.post(reverse("ai:parla_chiedi"), {"testo": "sì", "apertura": saluto.pk})
    assert r.status_code == 400 and r.json()["errore"] == "Questa chat è dell'azienda Bianchi Spa: passa a Bianchi Spa per continuare."
    assert not Turno.objects.exists()


def test_chiedi_ad_ada_su_una_chat_di_un_altra_azienda(client, p):
    from askada.models import Domanda
    p["u"].user_permissions.add(Permission.objects.get(codename="add_domanda", content_type__app_label="askada"))
    client.force_login(User.objects.get(pk=p["u"].pk))
    r = client.post(reverse("askada:chiedi"), {"testo": "quante fatture?", "conversazione": p["chat_b"].pk, "url": "/"},
                    HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and "Questa chat è dell'azienda Bianchi Spa: passa a Bianchi Spa per continuare." in unescape(r.content.decode())
    assert not Turno.objects.exists() and not Domanda.objects.exists()
    r = client.post(reverse("askada:chiedi"), {"testo": "e qui?", "conversazione": p["chat_r"].pk, "url": "/"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 200 and Turno.objects.filter(conversazione=p["chat_r"]).exists()       # la propria azienda sì


# --- scrivere in una chat di un'altra azienda ---

def test_invio_su_una_chat_di_un_altra_azienda_rifiutato(client, p):
    atteso = "Questa chat è dell'azienda Bianchi Spa: passa a Bianchi Spa per continuare."
    url = reverse("ai:invia_conversazione", args=[p["chat_b"].pk])
    r = client.post(url, {"testo": "fatturato del mese?"}, HTTP_HX_REQUEST="true")
    assert r.status_code == 204 and json.loads(r.headers["HX-Trigger"]) == {"ai-errore": atteso}
    r = client.post(url, {"testo": "fatturato del mese?"})
    assert r.status_code == 302 and r.url == reverse("ai:conversazione", args=[p["chat_b"].pk])
    assert atteso in unescape(client.get(r.url).content.decode())         # il messaggio sulla pagina «Passa a …»
    assert not Turno.objects.exists() and not MessaggioChat.objects.exists()


def test_rigenera_modifica_e_sposta_rifiutati_su_una_chat_di_un_altra_azienda(client, p):
    domanda = MessaggioChat.objects.create(conversazione=p["chat_b"], ruolo=MessaggioChat.UTENTE, testo="domanda")
    MessaggioChat.objects.create(conversazione=p["chat_b"], ruolo=MessaggioChat.ASSISTENTE, testo="risposta")
    client.post(reverse("ai:rigenera", args=[p["chat_b"].pk]))
    client.post(reverse("ai:modifica_messaggio", args=[domanda.pk]), {"testo": "altra domanda"})
    domanda.refresh_from_db()
    assert not Turno.objects.exists() and domanda.testo == "domanda" and p["chat_b"].messaggi.count() == 2
    r = client.post(reverse("ai:sposta", args=[p["chat_b"].pk]), {"progetto": p["area_r"].pk})
    p["chat_b"].refresh_from_db()
    assert p["chat_b"].progetto == p["area_b"]                           # un'area non cambia azienda
    pagina = unescape(client.get(r.url).content.decode())
    assert "Questa chat è dell'azienda Bianchi Spa: passa a Bianchi Spa per continuare." in pagina


def test_chat_nuova_da_un_area_di_un_altra_azienda_rifiutata(client, p):
    r = client.post(reverse("ai:invia"), {"testo": "ciao", "progetto": p["area_b"].pk}, HTTP_HX_REQUEST="true")
    assert r.status_code == 204
    assert json.loads(r.headers["HX-Trigger"]) == {"ai-errore": "Quest'area è dell'azienda Bianchi Spa: passa a Bianchi Spa per continuare."}
    assert Conversazione.objects.count() == 2 and not Turno.objects.exists()


def test_chat_nuova_nell_area_corrente_senza_cercarla_altrove(client, p, monkeypatch):
    monkeypatch.setattr(pagine, "_area_altrove", lambda request, pk: pytest.fail("cercata altrove un'area della corrente"))
    client.post(reverse("ai:invia"), {"testo": "ciao", "progetto": p["area_r"].pk}, HTTP_HX_REQUEST="true")
    assert Conversazione.objects.filter(progetto=p["area_r"]).count() == 2


def test_dopo_il_cambio_si_scrive(client, p):
    client.post(reverse("core:cambia_azienda"), {"azienda": p["bianchi"].pk, "next": "/"})
    client.post(reverse("ai:invia_conversazione", args=[p["chat_b"].pk]), {"testo": "fatturato del mese?"})
    assert Turno.objects.filter(conversazione=p["chat_b"]).exists()
    assert client.post(reverse("ai:invia_conversazione", args=[p["chat_r"].pk]), {"testo": "e qui?"},
                       HTTP_HX_REQUEST="true").status_code == 204                   # ora è Rossi a essere un'altra azienda
    assert not Turno.objects.filter(conversazione=p["chat_r"]).exists()


def test_chat_di_un_azienda_che_non_si_ha_piu(client, p):
    """Si apre come prima, ma Ada non ci risponde con i dati dell'azienda corrente."""
    p["u"].profilo.aziende.set([p["rossi"]])
    assert client.get(reverse("ai:conversazione", args=[p["chat_b"].pk])).status_code == 200
    r = client.post(reverse("ai:invia_conversazione", args=[p["chat_b"].pk]), {"testo": "ciao"}, HTTP_HX_REQUEST="true")
    motivo = json.loads(r.headers["HX-Trigger"])["ai-errore"]
    assert motivo == "Questa chat è dell'azienda Bianchi Spa, dove non puoi usare la chat: per continuare apri una chat nuova."
    assert not Turno.objects.exists()


def test_chat_senza_area_come_prima(client, p):
    vecchia = Conversazione.objects.create(utente=p["u"], titolo="Vecchia")
    assert client.get(reverse("ai:conversazione", args=[vecchia.pk])).status_code == 200
    client.post(reverse("ai:invia_conversazione", args=[vecchia.pk]), {"testo": "ciao"})
    assert Turno.objects.filter(conversazione=vecchia).exists()


# --- cronologia, preferiti e nome dell'azienda ---

def test_cronologia_e_preferiti_con_l_azienda_e_il_cambio(client, p):
    documento = documenti_chat.crea(p["chat_b"], p["u"], p["bianchi"], "Offerta Bianchi", "testo")
    documento.salvato = True
    documento.save(update_fields=["salvato"])
    html = unescape(client.get(reverse("ai:chat")).content.decode())
    url_r, url_b = reverse("ai:conversazione", args=[p["chat_r"].pk]), reverse("ai:conversazione", args=[p["chat_b"].pk])
    cerca = unescape(client.get(reverse("ai:cerca_chat"), {"q": "Chat di"}).content.decode())
    for elenco in (_pannello(html, "storico"), _pannello(html, "preferite").split("ai-preferiti-gruppo")[1], cerca):
        assert f'data-cambia-azienda="{p["bianchi"].pk}"' in _link(elenco, url_b)
        assert "data-cambia-azienda" not in _link(elenco, url_r)
        voce_b = elenco.split(f'href="{url_b}"')[1].split("</li>")[0]
        voce_r = elenco.split(f'href="{url_r}"')[1].split("</li>")[0]
        assert 'class="ai-elenco-azienda">Bianchi Spa<' in voce_b and 'class="ai-elenco-azienda">Rossi Srl<' in voce_r
    url_doc = f"{url_b}?documento={documento.pk}"
    preferiti = _pannello(html, "preferite")
    assert f'data-cambia-azienda="{p["bianchi"].pk}"' in _link(preferiti, url_doc) and "Bianchi Spa" in preferiti.split(f'href="{url_doc}"')[1].split("</li>")[0]


def test_l_azienda_accanto_al_nome_dell_area(client, p):
    personale = aree.personale(p["u"], p["rossi"])
    html = unescape(client.get(reverse("ai:progetto", args=[personale.pk])).content.decode())
    titolo = html.split('class="ai-progetto-titolo"')[1].split("</div>")[0]
    assert "Il mio spazio" in titolo and 'class="ai-area-azienda" title="Azienda dell\'area">Rossi Srl<' in titolo
    barra = unescape(client.get(reverse("ai:conversazione", args=[p["chat_r"].pk])).content.decode()).split('class="ai-barra-area"')[1].split("</div>")[0]
    assert "Commessa Alfa" in barra and 'class="ai-area-azienda" title="Azienda dell\'area">Rossi Srl<' in barra
