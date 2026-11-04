import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from core import allegati, cifratura
from core.models import Parametro
from discuss import connettori, ia, sandbox, servizi
from discuss.models import Connessione, ConversazioneEsterna, Notifica, SandboxEvento, SandboxMedia, Sportello, VoceConoscenza


def _utente(nome, *altri):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x", first_name=nome.capitalize())
    u.user_permissions.set(Permission.objects.filter(codename__in=["view_canale", "add_messaggio", *altri]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def op(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    return _utente("olga")


@pytest.fixture
def s(op, monkeypatch):
    monkeypatch.setattr("ai.conoscenza.embedding", lambda testi, tipo="document": None)
    x = Sportello.objects.create(nome="Assistenza")
    x.operatori.add(op)
    return x


@pytest.fixture
def wa(s):
    return Connessione.objects.create(tipo="whatsapp", nome="Numero", sportello=s, id_numero="111")


@pytest.fixture
def tg(s):
    return Connessione.objects.create(tipo="telegram", nome="Bot", sportello=s)


@pytest.fixture
def subito(monkeypatch):
    monkeypatch.setattr(connettori.transaction, "on_commit", lambda f, **k: f())


@pytest.fixture
def modello(monkeypatch):
    stato = {"risposta": "Risposta dell'AI", "testi": []}

    def genera(sistema, testo, *a, **k):
        stato["testi"].append(testo)
        return stato["risposta"]
    monkeypatch.setattr(ia, "genera", genera)
    return stato


def _manda(c, nome="foto.png", mime="image/png", dati=b"\x89PNG-prova", tipo="image", testo="", contatto=None):
    c = Connessione.objects.get(pk=c.pk)            # come un webhook vero: legge lo sportello di adesso
    contatto = contatto or ("393330000001" if c.tipo == "whatsapp" else "555")
    media = sandbox.conserva(c, nome, mime, dati)
    corpo, intest = sandbox.messaggio_cliente(c, contatto, "Mario", testo, tipo, media)
    assert connettori.ricevi(c, corpo, intest)[0] == 200
    return ConversazioneEsterna.objects.get(connessione=c, id_esterno=contatto)


def _reale(c):
    Connessione.objects.filter(pk=c.pk).update(sandbox=False, token_cifrato=cifratura.cifra("TOK"))
    return Connessione.objects.get(pk=c.pk)


@pytest.mark.parametrize("quale", ["wa", "tg"])
def test_foto_del_cliente_arriva_all_operatore(request, quale, op, client, subito):
    c = request.getfixturevalue(quale)
    conv = _manda(c, testo="Ecco il guasto")
    m = conv.canale.messaggi.get()
    a = allegati.di(m).get()
    assert m.corpo == "Ecco il guasto" and a.mime == ("image/png" if quale == "wa" else "image/jpeg") and a.file.open().read() == b"\x89PNG-prova"   # Telegram: foto sempre JPEG
    client.force_login(op)
    html = client.get(f"/discuss/c/{conv.canale_id}/").content.decode()
    assert f'<img src="{reverse("discuss:allegato", args=[a.pk])}"' in html
    assert client.get(reverse("discuss:allegato", args=[a.pk])).status_code == 200


def test_senza_didascalia_compare_un_etichetta(wa, subito):
    conv = _manda(wa)
    assert conv.canale.messaggi.get().corpo == "📎 Foto"


def test_nome_ed_estensione_non_li_decide_chi_manda(wa, subito):
    # un «documento» che si dichiara PDF ma si chiama .exe resta un PDF; un eseguibile vero non entra
    conv = _manda(wa, nome="fattura.exe", mime="application/pdf", tipo="document")
    assert allegati.di(conv.canale.messaggi.first()).get().nome == "fattura.pdf"
    conv2 = _manda(wa, nome="virus.exe", mime="application/x-msdownload", tipo="document", contatto="393330000002")
    assert not allegati.di(conv2.canale.messaggi.filter(autore_esterno="Mario").first()).exists()
    assert conv2.canale.messaggi.filter(tipo="sistema", corpo__contains="non è stato salvato").exists()
    uscite = SandboxEvento.objects.filter(verso="uscita", contatto="393330000002").values_list("testo", flat=True)
    assert any("Non sono riuscito a ricevere" in t for t in uscite)
    # niente HTML o SVG che il browser eseguirebbe
    conv3 = _manda(wa, nome="pagina.svg", mime="image/svg+xml", tipo="document", contatto="393330000003")
    assert not allegati.di(conv3.canale.messaggi.filter(autore_esterno="Mario").first()).exists()


def test_il_nome_viene_dal_tipo_anche_fuori_dall_elenco():
    assert connettori._nome_file("", "audio/wav", "voice", "abc").endswith(".wav")
    assert connettori._nome_file("", "audio/ogg; codecs=opus", "voice", "abc").startswith("messaggio-vocale-") 
    assert connettori._nome_file("", "audio/ogg; codecs=opus", "voice", "abc").endswith(".ogg")
    assert connettori._nome_file("x.exe", "application/x-msdownload", "document", "abc").endswith((".exe", ".bin"))


def test_troppo_grande_o_scomparso(wa, subito, settings):
    conv = _manda(wa, dati=b"")                                                   # vuoto
    assert conv.canale.messaggi.filter(tipo="sistema").exists()
    m = servizi.invia(conv.canale, None, "x", esterno="Mario", silenzioso=True)
    assert connettori.scarica_media(m.pk, "non-esiste", "image/png", "", "image") == "rifiutato"


def test_errore_temporaneo_si_ritenta(wa, subito, settings):
    settings.LAVORI_SINCRONI = False
    conv = _manda(wa)
    m = conv.canale.messaggi.get()
    id_media = SandboxMedia.objects.get().id_media
    Connessione.objects.filter(pk=wa.pk).update(sandbox_guasto="limite")
    with pytest.raises(connettori.ErroreConsegna):
        connettori.scarica_media(m.pk, id_media, "image/png", "", "image")
    Connessione.objects.filter(pk=wa.pk).update(sandbox_guasto="")
    assert connettori.scarica_media(m.pk, id_media, "image/png", "", "image") == "salvato" and allegati.di(m).count() == 1


def test_con_l_ai_una_foto_senza_testo_va_a_una_persona(s, wa, op, subito, modello):
    Sportello.objects.filter(pk=s.pk).update(modalita="ai")
    conv = _manda(wa)
    conv.refresh_from_db()
    assert conv.gestita_da == "persona" and modello["testi"] == []
    assert Notifica.objects.filter(utente=op, titolo__contains="ha bisogno di una persona").exists()


def test_con_l_ai_la_didascalia_riceve_risposta(s, wa, subito, modello):
    Sportello.objects.filter(pk=s.pk).update(modalita="ai")
    VoceConoscenza.objects.create(sportello=s, titolo="Garanzia", testo="Garanzia di 12 mesi")
    conv = _manda(wa, testo="La garanzia copre questo guasto?")
    conv.refresh_from_db()
    assert conv.gestita_da == "ai" and "La garanzia copre" in modello["testi"][0]
    assert conv.canale.messaggi.filter(da_ai=True, corpo="Risposta dell'AI").exists()


def test_il_vocale_si_trascrive_e_l_ai_risponde(s, tg, subito, modello, monkeypatch):
    Sportello.objects.filter(pk=s.pk).update(modalita="ai")
    Parametro.objects.update_or_create(chiave="discuss.url_trascrizione", azienda=None, defaults={"valore": "http://finto"})
    monkeypatch.setattr(ia, "trascrivi_file", lambda a: "Quanto costa il piano?")
    conv = _manda(tg, nome="voce.ogg", mime="audio/ogg", dati=b"OggS", tipo="voice")
    m = conv.canale.messaggi.filter(autore_esterno="Mario").get()
    assert m.corpo == "📎 Messaggio vocale" and m.trascrizione == "Quanto costa il piano?"
    assert "Quanto costa il piano?" in modello["testi"][0] and conv.canale.messaggi.filter(da_ai=True, corpo="Risposta dell'AI").exists()
    # non si capisce nulla: una persona
    monkeypatch.setattr(ia, "trascrivi_file", lambda a: "")
    conv2 = _manda(tg, nome="voce.ogg", mime="audio/ogg", dati=b"OggS", tipo="voice", contatto="556")
    conv2.refresh_from_db()
    assert conv2.gestita_da == "persona"


def test_whatsapp_reale_scarica_col_token_solo_dagli_host_di_meta(wa, monkeypatch):
    c = _reale(wa)
    viste = []

    def get(url, **k):
        viste.append(("get", url, k["headers"]["Authorization"]))
        return type("R", (), {"status_code": 200, "json": lambda s: {"url": "https://lookaside.fbsbx.com/whatsapp/abc", "mime_type": "image/jpeg"}})()
    monkeypatch.setattr(connettori.httpx, "get", get)
    monkeypatch.setattr(connettori, "_scarica_url", lambda url, intest: viste.append(("file", url, intest["Authorization"])) or b"JPEG")
    assert connettori.scarica(c, "M1") == (b"JPEG", "image/jpeg")
    assert viste[0][1].endswith("/M1") and viste[1] == ("file", "https://lookaside.fbsbx.com/whatsapp/abc", "Bearer TOK")
    # un indirizzo che non è di Meta non riceve il token, neanche travestito
    for falso in ("https://evil.example/x", "https://fbsbx.com.evil.example/x", "http://lookaside.fbsbx.com/x", "https://evilfbsbx.com/x"):
        monkeypatch.setattr(connettori.httpx, "get", lambda url, f=falso, **k: type("R", (), {"status_code": 200, "json": lambda s, f=f: {"url": f}})())
        chiamate = []
        monkeypatch.setattr(connettori, "_scarica_url", lambda *a: chiamate.append(a) or b"x")
        with pytest.raises(connettori.ErroreConsegna):
            connettori.scarica(c, "M2")
        assert chiamate == []


def test_telegram_reale_scarica_e_rifiuta_percorsi_strani(tg, monkeypatch):
    c = _reale(tg)
    monkeypatch.setattr(connettori.httpx, "get", lambda url, **k: type("R", (), {"status_code": 200, "json": lambda s: {"ok": True, "result": {"file_path": "photos/f.jpg"}}})())
    viste = []
    monkeypatch.setattr(connettori, "_scarica_url", lambda url, intest: viste.append(url) or b"J")
    assert connettori.scarica(c, "F")[0] == b"J" and viste == ["https://api.telegram.org/file/botTOK/photos/f.jpg"]
    monkeypatch.setattr(connettori.httpx, "get", lambda url, **k: type("R", (), {"status_code": 200, "json": lambda s: {"ok": True, "result": {"file_path": "../../etc"}}})())
    with pytest.raises(connettori.ErroreConsegna):
        connettori.scarica(c, "F")


def _con_file(conv, op, nome="foto.png", dati=b"PNG", testo="Ecco"):
    return servizi.invia(conv.canale, op, testo, [SimpleUploadedFile(nome, dati)])


def test_l_operatore_manda_un_file_su_whatsapp_reale(wa, op, monkeypatch):
    c = _reale(wa)
    corpo, intest = sandbox.messaggio_cliente(wa, "393331", "Mario", "Ciao")
    connettori.ricevi(c, corpo, intest)
    conv = ConversazioneEsterna.objects.get()
    m = _con_file(conv, op)
    fatte = []

    def post(url, **k):
        fatte.append((url, k))
        if url.endswith("/media"):
            return type("R", (), {"status_code": 200, "json": lambda s: {"id": "MEDIA9"}})()
        return type("R", (), {"status_code": 200, "json": lambda s: {"messages": [{"id": f"wamid.{len(fatte)}"}]}})()
    monkeypatch.setattr(connettori.httpx, "post", post)
    assert connettori.consegna(m.pk) == "inviato"
    assert fatte[0][1]["json"]["text"]["body"] == "Ecco"                           # prima il testo
    assert fatte[1][0].endswith("/111/media") and fatte[1][1]["files"]["file"][0] == "foto.png" and fatte[1][1]["data"]["messaging_product"] == "whatsapp"
    assert fatte[2][1]["json"]["type"] == "image" and fatte[2][1]["json"]["image"] == {"id": "MEDIA9"} and fatte[2][1]["json"]["to"] == "393331"


def test_l_operatore_manda_un_file_su_telegram_reale(tg, op, monkeypatch):
    c = _reale(tg)
    corpo, intest = sandbox.messaggio_cliente(tg, "555", "Mario", "Ciao")
    connettori.ricevi(c, corpo, intest)
    conv = ConversazioneEsterna.objects.get()
    fatte = []
    monkeypatch.setattr(connettori.httpx, "post", lambda url, **k: fatte.append((url, k)) or type("R", (), {"status_code": 200, "json": lambda s: {"ok": True, "result": {"message_id": 5}}})())
    assert connettori.consegna(_con_file(conv, op, testo="").pk) == "inviato"
    assert fatte[0][0] == "https://api.telegram.org/botTOK/sendPhoto" and fatte[0][1]["data"] == {"chat_id": "555"} and "photo" in fatte[0][1]["files"]
    assert connettori.consegna(_con_file(conv, op, nome="listino.pdf", testo="").pk) == "inviato"
    assert fatte[1][0].endswith("/sendDocument") and fatte[1][1]["files"]["document"][0] == "listino.pdf"


def test_ritentando_non_si_rimanda_cio_che_e_gia_arrivato(wa, op):
    corpo, intest = sandbox.messaggio_cliente(wa, "393331", "Mario", "Ciao")
    connettori.ricevi(wa, corpo, intest)
    conv = ConversazioneEsterna.objects.get()
    m = _con_file(conv, op)
    originale = connettori._invia_file

    def guasto(*a):
        raise connettori.ErroreConsegna("giù", temporaneo=True)
    connettori._invia_file = guasto
    try:
        with pytest.raises(connettori.ErroreConsegna):
            connettori.consegna(m.pk)
    finally:
        connettori._invia_file = originale
    m.refresh_from_db()
    assert m.consegna == "errore" and m.parti_inviate == ["testo"]
    assert connettori.consegna(m.pk) == "inviato"
    uscite = list(SandboxEvento.objects.filter(verso="uscita").values_list("testo", flat=True))
    assert uscite.count("Ecco") == 1 and any(t.startswith("[image] foto.png") for t in uscite)


def test_sandbox_file_e_permessi(client, wa, op):
    r = _utente("rino", "view_connessione", "change_connessione")
    client.force_login(r)
    url = reverse("discuss:sandbox_azione", args=[wa.pk])
    j = client.post(url, {"fa": "foto", "contatto": "393330000001", "nome": "Mario"}).json()
    media = j["eventi"][0]["media"]
    assert media["immagine"] and client.get(media["url"]).content.startswith(b"\x89PNG")
    # un file caricato che non è un'immagine si scarica, non si apre nella pagina
    j = client.post(url, {"fa": "file", "contatto": "393330000001", "file": SimpleUploadedFile("x.html", b"<script>1</script>", content_type="text/html")}).json()
    risposta = client.get(next(e for e in j["eventi"] if e["media"] and e["media"]["nome"] == "x.html")["media"]["url"])
    assert risposta["Content-Type"] == "application/octet-stream" and risposta["Content-Disposition"] == "attachment"
    altro = Client()
    altro.force_login(_utente("ugo"))
    assert altro.get(media["url"]).status_code == 403
    Connessione.objects.filter(pk=wa.pk).update(sandbox=False)
    assert client.get(media["url"]).status_code == 404
