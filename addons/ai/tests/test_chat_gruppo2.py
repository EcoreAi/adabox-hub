"""Memoria, progetti, ricerca sul web, immagini e scelta del modello: soprattutto i loro confini."""
import base64
import json
from decimal import Decimal
from pathlib import Path

import httpx2 as httpx
import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ai import allegati_chat, catalogo, contesto_utente, motore, proposte, protezione
from ai.gateway import anthropic_api, esecuzione, openai_compat
from ai.models import (AnelloCatena, Conversazione, Evento, MemoriaUtente, Modello, Profilo, ProgettoChat, Proposta, Provider, Turno)
from ai.strumenti import Contesto, disponibili, memoria, web
from ai.strumenti.conoscenza import leggi_allegato
from ai.strumenti.registro import ErroreStrumento
from core import allegati, rete
from core.allegati import AllegatoNonValido
from core.models import Allegato, Azienda

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 30


def _utente(nome, azienda):
    u = User.objects.create_user(nome, password="x", first_name=nome)
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(db, client, monkeypatch, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto", prezzo_input=Decimal(1), prezzo_output=Decimal(1))
    for compito in ("chat", "titoli"):
        AnelloCatena.objects.create(profilo=Profilo.objects.create(nome=compito, compito=compito), modello=modello, ordine=1)
    a, b = Azienda.objects.first(), Azienda.objects.create(nome="Altra")
    u = _utente("anna", a)
    client.force_login(u)
    return {"u": u, "az": a, "altra": b, "modello": modello, "provider": provider}


def _ctx(s, c=None, azienda=None):
    return Contesto(utente=s["u"], azienda=azienda or s["az"], conversazione=c)


def _chat(s, **extra):
    return Conversazione.objects.create(utente=s["u"], titolo="x", **extra)


# --- ricerca sul web ---

@pytest.fixture
def web_acceso(monkeypatch):
    valori = {"ai.url_ricerca_web": "http://searxng:8080", "ai.ricerca_web": True, "ai.url_pii": ""}
    monkeypatch.setattr(web.parametri, "leggi", lambda chiave, azienda=None: valori[chiave])
    monkeypatch.setattr(protezione, "impostazioni", lambda: ("", ()))
    return valori


def _motore(voci, viste=None):
    viste = viste if viste is not None else []

    def gestore(r):
        viste.append(r)
        return httpx.Response(200, json={"results": voci})
    return httpx.Client(transport=httpx.MockTransport(gestore))


def test_web_spento_di_default_e_niente_strumenti(s):
    nomi = {x.nome for x in web.filtra(disponibili(s["u"]), s["az"])}
    assert "cerca_web" not in nomi and "leggi_pagina" not in nomi
    with pytest.raises(ErroreStrumento, match="non è attiva"):
        web.cerca_web(_ctx(s, _chat(s)), "norme iva")


def test_web_con_azienda_spenta_non_passa(s, web_acceso):
    web_acceso["ai.ricerca_web"] = False
    assert not web.abilitata(s["az"])


def test_ricerca_e_risultati(s, web_acceso):
    viste = []
    dati = web.cerca_web(_ctx(s, _chat(s)), "aliquota iva 2026", http_client=_motore([{"title": "T", "url": "https://x.it/a", "content": "c"}, {"title": "no", "url": "javascript:alert(1)"}], viste))
    assert "format=json" in str(viste[0].url) and "aliquota" in str(viste[0].url)
    assert dati["risultati"] == [{"titolo": "T", "url": "https://x.it/a", "estratto": "c"}]


def test_i_dati_personali_della_chat_non_escono_nella_query(s, web_acceso):
    c = _chat(s, segnaposto={"[FULLNAME_1]": "Mario Rossi"})
    viste = []
    with pytest.raises(ErroreStrumento, match="dato personale"):
        web.cerca_web(_ctx(s, c), "contratto di MARIO ROSSI", http_client=_motore([], viste))
    assert not viste


def test_il_servizio_trova_un_dato_personale_e_blocca(s, web_acceso, monkeypatch):
    monkeypatch.setattr(protezione, "impostazioni", lambda: ("http://pii", ()))
    monkeypatch.setattr(protezione, "spans", lambda u, t, e: [(7, 26, "EMAIL")])
    viste = []
    with pytest.raises(ErroreStrumento, match="dato personale"):
        web.cerca_web(_ctx(s, _chat(s)), "cerca: mario@example.com xx", http_client=_motore([], viste))
    assert not viste


def test_nomi_di_aziende_si_possono_cercare(s, web_acceso, monkeypatch):
    monkeypatch.setattr(protezione, "impostazioni", lambda: ("http://pii", ()))
    monkeypatch.setattr(protezione, "spans", lambda u, t, e: [(0, 4, "ORG")])
    assert web.cerca_web(_ctx(s, _chat(s)), "Eni bilancio", http_client=_motore([{"title": "t", "url": "https://x.it"}]))


def test_controllo_giu_niente_ricerca(s, web_acceso, monkeypatch):
    monkeypatch.setattr(protezione, "impostazioni", lambda: ("http://pii", ()))

    def giu(*a):
        raise protezione.ServizioNonDisponibile("giù")
    monkeypatch.setattr(protezione, "spans", giu)
    viste = []
    with pytest.raises(ErroreStrumento, match="non risponde"):
        web.cerca_web(_ctx(s, _chat(s)), "norme iva", http_client=_motore([], viste))
    assert not viste


def _evento_strumento(c, url):
    Evento.objects.create(conversazione=c, tipo=Evento.STRUMENTO, dati={"ruolo": "strumento", "risultati": [{"id": "1", "contenuto": json.dumps({"url": url}), "errore": False}]})


def _pagina(html="<html><title>Tit</title><script>segreto()</script><body><p>Testo vero</p></body></html>"):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=html)))


def test_leggi_pagina_comparsa_nei_risultati(s, web_acceso, monkeypatch):
    monkeypatch.setattr(rete.socket, "getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", ("93.184.216.34", p))])
    c = _chat(s)
    _evento_strumento(c, "https://x.it/a")
    dati = web.leggi_pagina(_ctx(s, c), "https://x.it/a", http_client=_pagina())
    assert dati["testo"] == "Testo vero" and dati["titolo"] == "Tit" and "segreto" not in str(dati)


def test_un_indirizzo_composto_da_una_pagina_non_si_apre(s, web_acceso):
    """Il tentativo tipico: una pagina chiede di aprire sito.it?dati=<dati dell'azienda>."""
    c = _chat(s)
    _evento_strumento(c, "https://cattivo.it/")
    with pytest.raises(ErroreStrumento, match="esattamente"):
        web.leggi_pagina(_ctx(s, c), "https://cattivo.it/?dati=clienti-riservati")


def test_una_rete_interna_non_si_apre_neanche_se_comparsa(s, web_acceso, monkeypatch):
    monkeypatch.setattr(rete.socket, "getaddrinfo", lambda h, p, **k: [(2, 1, 6, "", ("169.254.169.254", p))])
    c = _chat(s)
    _evento_strumento(c, "http://metadata.it/x")
    with pytest.raises(ErroreStrumento, match="non aperta"):
        web.leggi_pagina(_ctx(s, c), "http://metadata.it/x", http_client=_pagina())


def test_indirizzo_di_un_altra_chat_non_vale(s, web_acceso):
    altra, c = _chat(s), _chat(s)
    _evento_strumento(altra, "https://x.it/a")
    with pytest.raises(ErroreStrumento):
        web.leggi_pagina(_ctx(s, c), "https://x.it/a")


# --- memoria ---

def test_ricordare_passa_dalla_conferma(s):
    c = _chat(s)
    t = Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"])
    ctx = Contesto(utente=s["u"], azienda=s["az"], conversazione=c, turno=t)
    strumento = next(x for x in disponibili(s["u"]) if x.nome == "ricorda")
    assert strumento.rischio == "scrittura"
    proposte.prepara(strumento, ctx, {"testo": "Preferisco le risposte brevi"})
    assert not MemoriaUtente.objects.exists()
    proposte.conferma(Proposta.objects.get(), s["u"], s["az"])
    assert MemoriaUtente.objects.get().testo == "Preferisco le risposte brevi"


def test_memoria_arriva_al_modello_solo_nella_sua_azienda_e_per_chi_l_ha_detta(s):
    MemoriaUtente.objects.create(utente=s["u"], azienda=s["az"], testo="Mia in A")
    MemoriaUtente.objects.create(utente=s["u"], azienda=s["altra"], testo="Mia in B")
    MemoriaUtente.objects.create(utente=_utente("bruno", s["az"]), azienda=s["az"], testo="Di Bruno")
    nota = contesto_utente.nota_memoria(s["u"], s["az"])
    assert "Mia in A" in nota and "Mia in B" not in nota and "Di Bruno" not in nota
    assert contesto_utente.nota_memoria(s["u"], None) == ""
    c = _chat(s)
    motore.avvia(c, "ciao", s["u"], s["az"], sincrono=True)
    assert "Mia in A" in c.eventi.filter(tipo=Evento.UTENTE).get().dati["testo"]


def test_memoria_ha_un_tetto(s):
    for i in range(40):
        MemoriaUtente.objects.create(utente=s["u"], azienda=s["az"], testo="x" * 200)
    assert len(contesto_utente.nota_memoria(s["u"], s["az"])) < contesto_utente.MASSIMO_CARATTERI + 300


def test_memoria_troppo_lunga_o_vuota(s):
    with pytest.raises(ErroreStrumento):
        memoria.anteprima_ricorda(_ctx(s), "x" * 501)
    with pytest.raises(ErroreStrumento):
        memoria.anteprima_ricorda(_ctx(s), "   ")


def test_pagina_memoria_solo_le_proprie_anche_per_il_superuser(client, s):
    mia = MemoriaUtente.objects.create(utente=s["u"], azienda=s["az"], testo="MIA")
    root = User.objects.create_superuser("root", "r@example.com", "x")
    root.profilo.aziende.set([s["az"]])
    root.profilo.azienda_predefinita = s["az"]
    root.profilo.save()
    client.force_login(root)
    assert "MIA" not in client.get("/ai/memoria/").content.decode()
    assert client.get(f"/ai/memoria/{mia.pk}/").status_code == 404
    client.force_login(s["u"])
    assert "MIA" in client.get("/ai/memoria/").content.decode()
    assert client.post(f"/ai/memoria/{mia.pk}/elimina/").status_code == 302
    assert not MemoriaUtente.objects.exists()


def test_memoria_scritta_a_mano(client, s):
    assert client.post("/ai/memoria/nuovo/", {"testo": "Scritta da me"}).status_code == 302
    m = MemoriaUtente.objects.get()
    assert m.utente == s["u"] and m.azienda == s["az"]


# --- progetti ---

def test_istruzioni_e_file_del_progetto_arrivano_alla_chat(client, s):
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Offerta", istruzioni="Rispondi in inglese")
    f = allegati.salva(p, SimpleUploadedFile("capitolato.txt", b"Scade a giugno"), s["u"])
    assert client.post(reverse("ai:invia"), {"testo": "ciao", "progetto": p.pk}).status_code == 302
    c = Conversazione.objects.get()
    testo = c.eventi.filter(tipo=Evento.UTENTE).get().dati["testo"]
    assert c.progetto == p and "Rispondi in inglese" in testo and f"allegato n. {f.pk}" in testo
    assert "giugno" in leggi_allegato(_ctx(s, c), f.pk)["testo"]


def test_i_file_di_un_progetto_non_valgono_per_altre_chat(s):
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="A")
    f = allegati.salva(p, SimpleUploadedFile("a.txt", b"x"), s["u"])
    with pytest.raises(ErroreStrumento):
        leggi_allegato(_ctx(s, _chat(s)), f.pk)


def test_progetto_di_un_altro_o_di_un_altra_azienda_non_si_usa(client, s):
    altrui = ProgettoChat.objects.create(utente=_utente("bruno", s["az"]), azienda=s["az"], nome="Di Bruno", istruzioni="SEGRETA")
    altra_az = ProgettoChat.objects.create(utente=s["u"], azienda=s["altra"], nome="In B", istruzioni="DI-B")
    for p in (altrui, altra_az):
        client.post(reverse("ai:invia"), {"testo": "ciao", "progetto": p.pk})
    for c in Conversazione.objects.all():
        assert c.progetto is None and "SEGRETA" not in str(c.eventi.first().dati)
    c = Conversazione.objects.first()
    client.post(reverse("ai:sposta", args=[c.pk]), {"progetto": altrui.pk})
    c.refresh_from_db()
    assert c.progetto is None
    assert client.get(f"/ai/progetti/{altrui.pk}/").status_code == 404


def test_pagina_progetto_e_nuova_chat(client, s):
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Offerta")
    assert client.get(f"/ai/progetti/{p.pk}/").status_code == 200
    pagina = client.get(reverse("ai:chat"), {"progetto": p.pk}).content.decode()
    assert "Nuova chat nel progetto" in pagina and "Offerta" in pagina


def test_eliminando_un_progetto_se_ne_vanno_i_file_e_le_chat_restano(client, s):
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="A")
    f = allegati.salva(p, SimpleUploadedFile("a.txt", b"x"), s["u"])
    percorso = Path(f.file.path)
    c = _chat(s, progetto=p)
    assert client.post(f"/ai/progetti/{p.pk}/elimina/").status_code == 302
    c.refresh_from_db()
    assert c.progetto is None and not Allegato.objects.exists() and not percorso.exists()


# --- immagini ---

def _png(nome="foto.png", dati=PNG):
    return SimpleUploadedFile(nome, dati)


def _immagini_cloud(monkeypatch, valore=True):
    monkeypatch.setattr(allegati_chat, "immagini_verso_il_cloud", lambda azienda: valore)


def test_immagini_spente_di_default_senza_modello_locale(s):
    Modello.objects.filter(pk=s["modello"].pk).update(visione=False)
    with pytest.raises(AllegatoNonValido, match="non si mascherano"):
        allegati_chat.controlla([_png()], s["az"])


def test_finta_immagine_rifiutata(s, monkeypatch):
    _immagini_cloud(monkeypatch)
    with pytest.raises(AllegatoNonValido, match="non è davvero"):
        allegati_chat.controlla([_png(dati=b"<html>non sono un png")], s["az"])


def test_immagine_troppo_grande(s, monkeypatch):
    _immagini_cloud(monkeypatch)
    with pytest.raises(AllegatoNonValido, match="MB"):
        allegati_chat.controlla([_png(dati=PNG + b"0" * (6 * 1024 * 1024))], s["az"])


def test_immagine_ammessa_ha_il_formato_giusto_per_i_due_fornitori():
    m = [{"ruolo": "utente", "testo": "cosa vedi", "immagini_dati": [{"mime": "image/png", "dati": "QUJD"}]}]
    a = anthropic_api._messaggi(m)[0]["content"]
    assert a[0] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}} and a[1]["text"] == "cosa vedi"
    o = openai_compat._messaggi("sys", m)[1]["content"]
    assert o[0]["image_url"]["url"] == "data:image/png;base64,QUJD" and o[1]["text"] == "cosa vedi"


def test_solo_l_ultima_immagine_recente_va_al_modello(s):
    c = _chat(s)
    m = c.messaggi.create(ruolo="utente", testo="x")
    a = allegati.salva(m, _png(), s["u"])
    voci = [{"ruolo": "utente", "testo": "con foto", "immagini": [a.pk]}, {"ruolo": "assistente", "blocchi": []}]
    copia, con, ultimo = allegati_chat.con_immagini(voci + [{"ruolo": "utente", "testo": "seguito"}])
    assert con and not ultimo and base64.b64decode(copia[0]["immagini_dati"][0]["dati"]) == PNG
    molti = voci + [{"ruolo": "utente", "testo": str(i)} for i in range(allegati_chat.MESSAGGI_IMMAGINE)]
    assert allegati_chat.con_immagini(molti)[1] is False


def test_senza_modelli_ammessi_il_turno_lo_dice(client, s, monkeypatch):
    _immagini_cloud(monkeypatch, True)
    client.post(reverse("ai:invia"), {"testo": "cosa vedi", "allegati": [_png()]})
    c = Conversazione.objects.get()
    assert "immagini" in c.eventi.filter(tipo=Evento.UTENTE).get().dati
    assert "leggere questa immagine" in c.messaggi.filter(ruolo="assistente").get().testo


def test_con_un_modello_che_legge_le_immagini_arrivano(client, s, monkeypatch):
    Modello.objects.filter(pk=s["modello"].pk).update(visione=True)
    visti = []

    def adattatore(modello, chiave, **richiesta):
        visti.append(richiesta["messaggi"][-1])
        from ai.gateway.tipi import Fine, Testo
        yield Testo("Vedo una foto")
        yield Fine("fine", [{"tipo": "testo", "testo": "Vedo una foto"}])
    monkeypatch.setitem(esecuzione.ADATTATORI, "finto", adattatore)
    client.post(reverse("ai:invia"), {"testo": "cosa vedi", "allegati": [_png()]})
    assert visti[0]["immagini_dati"][0]["mime"] == "image/png" and base64.b64decode(visti[0]["immagini_dati"][0]["dati"]) == PNG


def test_modello_cloud_senza_permesso_non_riceve_immagini(s):
    cloud = Modello(provider=Provider(nome="c", tipo="anthropic", locale=False), visione=True)
    assert not allegati_chat.modello_ammesso_per_immagini(cloud, s["az"])
    assert not allegati_chat.modello_ammesso_per_immagini(Modello(provider=Provider(locale=True), visione=False), s["az"])
    assert allegati_chat.modello_ammesso_per_immagini(Modello(provider=Provider(locale=True), visione=True), s["az"])


def test_immagine_non_si_legge_come_testo(s):
    c = _chat(s)
    a = allegati.salva(c.messaggi.create(ruolo="utente", testo="x"), _png(), s["u"])
    with pytest.raises(ErroreStrumento, match="immagine"):
        leggi_allegato(_ctx(s, c), a.pk)


# --- scelta del modello ---

def test_si_sceglie_solo_tra_i_modelli_abilitati(client, s):
    altro = Modello.objects.create(provider=s["provider"], id_api="finto-2", etichetta="Secondo", sceglibile=True)
    vietato = Modello.objects.create(provider=s["provider"], id_api="finto-3", etichetta="Vietato")
    pagina = client.get(reverse("ai:chat")).content.decode()
    assert "Secondo" in pagina and "Vietato" not in pagina
    client.post(reverse("ai:invia"), {"testo": "uno", "modello": altro.pk})
    c = Conversazione.objects.get()
    assert c.modello == altro and c.turni.filter(compito="chat").first().modello == altro
    client.post(reverse("ai:invia_conversazione", args=[c.pk]), {"testo": "due", "modello": vietato.pk})
    c.refresh_from_db()
    assert c.modello is None


def test_modello_non_piu_sceglibile_torna_la_catena_degli_amministratori(s):
    altro = Modello.objects.create(provider=s["provider"], id_api="finto-2", etichetta="Secondo", sceglibile=True)
    catena = [(s["modello"], "")]
    assert catalogo.con_scelta(catena, altro)[0][0] == altro and len(catalogo.con_scelta(catena, altro)) == 2
    Modello.objects.filter(pk=altro.pk).update(sceglibile=False)
    assert catalogo.con_scelta(catena, Modello.objects.get(pk=altro.pk)) == catena
    assert catalogo.con_scelta(catena, None) == catena


def test_senza_modelli_sceglibili_niente_menu(client, s):
    assert 'name="modello"' not in client.get(reverse("ai:chat")).content.decode()


# --- provenienza: un badge verde deve dire la verità ---

def _turno_con_lettura(s, strumento, contenuto="Aliquota 22"):
    from ai import provenienza
    c = _chat(s)
    t = Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"])
    Evento.objects.create(conversazione=c, turno=t, tipo=Evento.ASSISTENTE, dati={"ruolo": "assistente", "blocchi": [{"tipo": "strumento", "id": "a", "nome": strumento, "argomenti": {}}]})
    Evento.objects.create(conversazione=c, turno=t, tipo=Evento.STRUMENTO, dati={"ruolo": "strumento", "risultati": [{"id": "a", "contenuto": contenuto, "errore": False}]})
    return provenienza.calcola(t, "L'aliquota è 22")


def _badge(pv):
    from django.template.loader import render_to_string
    return render_to_string("ai/_provenienza.html", {"pv": pv})


@pytest.mark.parametrize("strumento,parola", [("cerca_web", "Dal web"), ("leggi_pagina", "Dal web"), ("leggi_allegato", "Dagli allegati")])
def test_web_e_allegati_non_risultano_dati_del_gestionale(s, strumento, parola):
    pv = _turno_con_lettura(s, strumento)
    html = _badge(pv)
    assert pv["letture"] == 0 and parola in html and "Dati dal gestionale" not in html and "Senza dati" not in html


def test_i_record_restano_dati_del_gestionale(s):
    pv = _turno_con_lettura(s, "cerca_record")
    assert pv["letture"] == 1 and pv["letture_web"] == 0 and "Dati dal gestionale" in _badge(pv)


def test_le_risposte_di_prima_si_mostrano_ancora(s):
    assert "Dati dal gestionale (2 letture)" in _badge({"esito": "verificato", "letture": 2, "strumenti": ["cerca_record"], "pii": 0})


def test_progetti_e_memoria_non_si_condividono_nelle_comunicazioni(client, s):
    p = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Mio")
    m = MemoriaUtente.objects.create(utente=s["u"], azienda=s["az"], testo="x")
    for url in (f"/ai/progetti/{p.pk}/", f"/ai/memoria/{m.pk}/"):
        pagina = client.get(url).content.decode()
        assert "discuss/condividi" not in pagina and "canale_record" not in pagina.replace("_", "")


def test_gli_altri_record_si_condividono_ancora(client, s):
    from contatti.models import Contatto
    s["u"].user_permissions.add(*Permission.objects.filter(codename__in=["view_contatto", "add_canale", "view_canale", "add_messaggio"]))
    client.force_login(User.objects.get(pk=s["u"].pk))
    c = Contatto.objects.create(azienda=s["az"], nome="X")
    assert "/discuss/condividi/" in client.get(f"/contatti/contatti/{c.pk}/").content.decode()
