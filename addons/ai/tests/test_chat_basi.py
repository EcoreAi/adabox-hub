"""Le basi della chat: allegati, rigenera e modifica, ricerca, rinomina, export, voto, testo formattato in diretta."""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ai import allegati_chat, flusso, markdown, motore
from ai.gateway import esecuzione
from ai.models import (AnelloCatena, Artifact, Conversazione, Evento, MessaggioChat, Modello, Profilo, Proposta, Provider, Turno,
                       ValutazioneRisposta)
from ai.motore.compattazione import messaggi as messaggi_del_modello
from ai.strumenti import Contesto
from ai.strumenti.conoscenza import leggi_allegato
from ai.strumenti.registro import ErroreStrumento
from core.allegati import AllegatoNonValido
from core.models import Allegato, Azienda


def _utente(nome):
    u = User.objects.create_user(nome, password="x", first_name=nome)
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.profilo.aziende.set([Azienda.objects.first()])
    u.profilo.azienda_predefinita = Azienda.objects.first()
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(db, client, monkeypatch, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    monkeypatch.setattr(esecuzione, "_dormi", lambda s: None)
    monkeypatch.setattr(flusso, "INTERVALLO", 0)
    provider = Provider.objects.create(nome="Finto", tipo="finto", locale=True)
    modello = Modello.objects.create(provider=provider, id_api="finto-1", etichetta="Finto", prezzo_input=Decimal(1), prezzo_output=Decimal(1))
    for compito in ("chat", "titoli"):
        AnelloCatena.objects.create(profilo=Profilo.objects.create(nome=compito, compito=compito), modello=modello, ordine=1)
    u = _utente("anna")
    client.force_login(u)
    return {"u": u, "az": Azienda.objects.first()}


def _file(nome="nota.txt", contenuto=b"Il contratto scade a marzo"):
    return SimpleUploadedFile(nome, contenuto)


def _chat(s, testi=("Prima domanda",)):
    c = Conversazione.objects.create(utente=s["u"], titolo="Prova")
    for t in testi:
        motore.avvia(c, t, s["u"], s["az"], sincrono=True)
    return c


def _testo_eventi(c):
    return [e.dati.get("testo", "") for e in c.eventi.filter(tipo=Evento.UTENTE)]


# --- allegati ---

def test_allegato_arriva_col_messaggio_e_il_modello_lo_sa(client, s):
    r = client.post(reverse("ai:invia"), {"testo": "Riassumi", "allegati": [_file()]})
    assert r.status_code == 302
    c = Conversazione.objects.get()
    m = c.messaggi.filter(ruolo="utente").get()
    a = allegati_chat.di(m)[0]
    assert a.nome == "nota.txt" and f"allegato n. {a.pk}" in _testo_eventi(c)[0]
    pagina = client.get(reverse("ai:conversazione", args=[c.pk])).content.decode()
    assert "nota.txt" in pagina and reverse("ai:allegato", args=[a.pk]) in pagina


def test_solo_il_file_senza_testo_si_puo_inviare(client, s):
    client.post(reverse("ai:invia"), {"testo": "", "allegati": [_file()]})
    assert MessaggioChat.objects.get(ruolo="utente").testo == "Guarda l'allegato."


@pytest.mark.parametrize("nome", ["foto.png", "virus.exe", "senza_estensione"])
def test_tipi_non_leggibili_rifiutati(db, nome):
    with pytest.raises(AllegatoNonValido):
        allegati_chat.controlla([_file(nome)])


def test_troppi_file_rifiutati():
    with pytest.raises(AllegatoNonValido):
        allegati_chat.controlla([_file(f"{i}.txt") for i in range(allegati_chat.MASSIMO + 1)])


def test_file_rifiutato_non_lascia_una_chat_a_meta(client, s):
    r = client.post(reverse("ai:invia"), {"testo": "x", "allegati": [_file("foto.png")]}, headers={"HX-Request": "true"})
    assert r.status_code == 204 and "ai-errore" in r["HX-Trigger"] and "foto.png" in json.loads(r["HX-Trigger"])["ai-errore"]
    assert not Conversazione.objects.exists() and not Turno.objects.exists()


def test_lo_strumento_legge_solo_gli_allegati_di_questa_chat(client, s):
    client.post(reverse("ai:invia"), {"testo": "uno", "allegati": [_file()]})
    c = Conversazione.objects.get()
    a = Allegato.objects.get()
    dati = leggi_allegato(Contesto(utente=s["u"], azienda=s["az"], conversazione=c), a.pk)
    assert "scade a marzo" in dati["testo"] and dati["pagine"] == 1
    altra = Conversazione.objects.create(utente=s["u"], titolo="Altra")
    with pytest.raises(ErroreStrumento, match="Nessun allegato"):
        leggi_allegato(Contesto(utente=s["u"], azienda=s["az"], conversazione=altra), a.pk)


def test_lo_strumento_non_apre_gli_allegati_di_altri_record(client, s):
    from contatti.models import Contatto
    from core import allegati
    contatto = Contatto.objects.create(azienda=s["az"], nome="X")
    file_altrui = allegati.salva(contatto, _file("riservato.txt", b"segreto"), s["u"])
    c = _chat(s)
    with pytest.raises(ErroreStrumento):
        leggi_allegato(Contesto(utente=s["u"], azienda=s["az"], conversazione=c), file_altrui.pk)


def test_file_senza_testo_lo_dice(s):
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    m = MessaggioChat.objects.create(conversazione=c, ruolo="utente", testo="x")
    from core import allegati
    a = allegati.salva(m, _file("scansione.pdf", b"non e un pdf"), s["u"])
    with pytest.raises(ErroreStrumento, match="scansione"):
        leggi_allegato(Contesto(utente=s["u"], azienda=s["az"], conversazione=c), a.pk)


def test_il_file_lo_scarica_solo_il_proprietario(client, s):
    client.post(reverse("ai:invia"), {"testo": "uno", "allegati": [_file()]})
    url = reverse("ai:allegato", args=[Allegato.objects.get().pk])
    assert client.get(url).status_code == 200
    client.force_login(_utente("bruno"))
    assert client.get(url).status_code == 404


def test_eliminando_la_chat_se_ne_vanno_i_file(client, s, settings):
    client.post(reverse("ai:invia"), {"testo": "uno", "allegati": [_file()]})
    a = Allegato.objects.get()
    percorso = Path(a.file.path)
    assert percorso.exists()
    client.post(reverse("ai:elimina", args=[Conversazione.objects.get().pk]))
    assert not Allegato.objects.exists() and not percorso.exists()


# --- rigenera e modifica ---

def test_rigenera_sostituisce_l_ultima_risposta(client, s):
    c = _chat(s)
    assert client.post(reverse("ai:rigenera", args=[c.pk])).status_code == 302
    assert c.messaggi.filter(ruolo="assistente").count() == 1 and c.messaggi.filter(ruolo="utente").count() == 1
    assert len(_testo_eventi(c)) == 1 and c.turni.filter(compito="chat").count() == 2      # il costo del primo turno resta


def test_modifica_toglie_cio_che_viene_dopo_e_il_modello_lo_dimentica(client, s):
    c = _chat(s, ["Domanda uno", "Domanda due"])
    prima = c.messaggi.filter(ruolo="utente").first()
    assert client.post(reverse("ai:modifica_messaggio", args=[prima.pk]), {"testo": "Domanda corretta"}).status_code == 302
    assert list(c.messaggi.values_list("testo", flat=True)) == ["Domanda corretta", "Risposta di prova (modello finto) a: Domanda corretta"]
    storia = json.dumps(messaggi_del_modello(c), ensure_ascii=False, default=str)
    assert "Domanda corretta" in storia and "Domanda due" not in storia and "Domanda uno" not in storia


def test_modifica_tiene_gli_allegati(client, s):
    client.post(reverse("ai:invia"), {"testo": "uno", "allegati": [_file()]})
    c = Conversazione.objects.get()
    m = c.messaggi.filter(ruolo="utente").get()
    client.post(reverse("ai:modifica_messaggio", args=[m.pk]), {"testo": "due"})
    assert allegati_chat.di(m) and "allegato n." in _testo_eventi(c)[0]


def _proposta(c, stato):
    turno = c.turni.filter(compito="chat").order_by("-pk").first()
    return Proposta.objects.create(conversazione=c, turno=turno, utente=c.utente, azienda=turno.azienda, strumento="crea_record",
                                   argomenti={}, titolo="Crea X", stato=stato)


def test_con_una_modifica_ai_dati_gia_eseguita_non_si_riparte(client, s):
    c = _chat(s)
    p = _proposta(c, Proposta.ESEGUITA)
    pagina = client.post(reverse("ai:rigenera", args=[c.pk]), follow=True).content.decode()
    assert "già stata eseguita" in pagina and c.messaggi.filter(ruolo="assistente").exists() and Proposta.objects.filter(pk=p.pk).exists()
    assert c.turni.filter(compito="chat").count() == 1


def test_le_proposte_in_attesa_si_annullano_ripartendo(client, s):
    c = _chat(s)
    p = _proposta(c, Proposta.IN_ATTESA)
    client.post(reverse("ai:rigenera", args=[c.pk]))
    p.refresh_from_db()
    assert p.stato == Proposta.ANNULLATA and p.comunicata
    assert "Crea X" not in _testo_eventi(c)[0]


def test_gli_artifact_salvati_restano(client, s):
    c = _chat(s)
    t = c.turni.filter(compito="chat").first()
    Artifact.objects.create(conversazione=c, turno=t, utente=s["u"], tipo="tabella", titolo="TIENIMI", salvato=True, spec={})
    Artifact.objects.create(conversazione=c, turno=t, utente=s["u"], tipo="tabella", titolo="VIA", spec={})
    client.post(reverse("ai:rigenera", args=[c.pk]))
    assert list(Artifact.objects.values_list("titolo", flat=True)) == ["TIENIMI"]


def test_non_si_riparte_con_una_risposta_in_corso(s):
    c = _chat(s)
    m = c.messaggi.filter(ruolo="utente").get()
    Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], battito="2099-01-01T00:00:00Z")
    with pytest.raises(motore.NonSiPuoRipartire, match="in corso"):
        motore.riparti(c, m, "x", s["u"], s["az"])


def test_la_chat_di_un_altro_non_si_tocca(client, s):
    c = _chat(s)
    m = c.messaggi.filter(ruolo="utente").get()
    r = c.messaggi.filter(ruolo="assistente").get()
    client.force_login(_utente("bruno"))
    for url, dati in ((reverse("ai:rigenera", args=[c.pk]), {}), (reverse("ai:modifica_messaggio", args=[m.pk]), {"testo": "y"}),
                      (reverse("ai:rinomina", args=[c.pk]), {"titolo": "y"}), (reverse("ai:voto", args=[r.pk]), {"voto": "1"})):
        assert client.post(url, dati).status_code == 404
    assert client.get(reverse("ai:esporta", args=[c.pk])).status_code == 404


def test_una_risposta_non_si_modifica_come_una_domanda(client, s):
    c = _chat(s)
    r = c.messaggi.filter(ruolo="assistente").get()
    assert client.post(reverse("ai:modifica_messaggio", args=[r.pk]), {"testo": "y"}).status_code == 404


# --- rinomina, ricerca, export ---

def test_rinomina_e_il_titolo_automatico_non_lo_tocca(client, s):
    c = _chat(s)
    client.post(reverse("ai:rinomina", args=[c.pk]), {"titolo": "  Il mio   titolo "})
    c.refresh_from_db()
    assert c.titolo == "Il mio titolo" and c.titolo_generato


def test_cerca_nel_titolo_e_nei_messaggi_solo_nelle_proprie(client, s):
    c = _chat(s, ["Parliamo di PAROLARARA"])
    Conversazione.objects.filter(pk=c.pk).update(titolo="Senza indizi")
    Conversazione.objects.create(utente=s["u"], titolo="Altra cosa")
    Conversazione.objects.create(utente=_utente("bruno"), titolo="PAROLARARA di Bruno")
    Conversazione.objects.create(utente=s["u"], titolo="PAROLARARA nascosta", nascosta=True)
    pagina = client.get(reverse("ai:cerca_chat"), {"q": "parolarara"}).content.decode()
    assert "Senza indizi" in pagina and "Altra cosa" not in pagina and "di Bruno" not in pagina and "nascosta" not in pagina
    assert "Nessuna chat trovata" in client.get(reverse("ai:cerca_chat"), {"q": "zzzz"}).content.decode()


def test_export_in_markdown(client, s):
    c = _chat(s, ["La domanda"])
    Conversazione.objects.filter(pk=c.pk).update(titolo='Titolo "strano"/x')
    r = client.get(reverse("ai:esporta", args=[c.pk]))
    testo = r.content.decode()
    assert r["Content-Type"].startswith("text/markdown") and "attachment" in r["Content-Disposition"] and ".md" in r["Content-Disposition"]
    assert "La domanda" in testo and "Risposta di prova" in testo and "## Tu" in testo and "## Assistente" in testo


# --- voto ---

def test_voto_su_giu_e_ripremere_lo_toglie(client, s):
    c = _chat(s)
    r = c.messaggi.filter(ruolo="assistente").get()
    url = reverse("ai:voto", args=[r.pk])
    assert client.post(url, {"voto": "1"}).status_code == 200
    v = ValutazioneRisposta.objects.get()
    assert v.voto == 1 and v.utente == s["u"] and v.azienda == s["az"] and v.domanda == "Prima domanda"
    pagina = client.post(url, {"voto": "-1"}).content.decode()
    assert ValutazioneRisposta.objects.get().voto == -1 and "Che cosa non andava" in pagina
    assert "Grazie" in client.post(url, {"commento": "Numeri sbagliati"}).content.decode()
    assert ValutazioneRisposta.objects.get().commento == "Numeri sbagliati"
    client.post(url, {"voto": "-1"})
    assert not ValutazioneRisposta.objects.exists()
    assert client.post(url, {"voto": "9"}).status_code == 400


def test_valutazioni_visibili_per_azienda_e_in_sola_lettura(client, s):
    c = _chat(s)
    client.post(reverse("ai:voto", args=[c.messaggi.filter(ruolo="assistente").get().pk]), {"voto": "-1"})
    v = ValutazioneRisposta.objects.get()
    altra = Azienda.objects.create(nome="Altra")
    bruno = User.objects.create_user("bruno", password="x")
    bruno.user_permissions.set(Permission.objects.filter(codename="view_valutazionerisposta"))
    bruno.profilo.aziende.set([altra])
    bruno.profilo.azienda_predefinita = altra
    bruno.profilo.save()
    client.force_login(User.objects.get(pk=bruno.pk))
    assert client.get(f"/ai/valutazioni/{v.pk}/").status_code == 404
    capo = User.objects.create_user("capo", password="x")
    capo.user_permissions.set(Permission.objects.filter(codename="view_valutazionerisposta"))
    capo.profilo.aziende.set([s["az"]])
    capo.profilo.azienda_predefinita = s["az"]
    capo.profilo.save()
    client.force_login(User.objects.get(pk=capo.pk))
    assert client.get("/ai/valutazioni/").status_code == 200
    pagina = client.get(f"/ai/valutazioni/{v.pk}/").content.decode()
    assert "Risposta di prova" in pagina and "Prima domanda" in pagina
    assert client.get(f"/ai/valutazioni/{v.pk}/modifica/").status_code == 403


# --- testo formattato ---

def _eventi(testo):
    voci = []
    for blocco in "".join(testo).strip().split("\n\n"):
        nome = next((r[7:] for r in blocco.splitlines() if r.startswith("event: ")), None)
        dati = next((r[6:] for r in blocco.splitlines() if r.startswith("data: ")), None)
        if nome:
            voci.append((nome, json.loads(dati)))
    return voci


def test_in_diretta_arriva_html_gia_sicuro(s):
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    t = Turno.objects.create(conversazione=c, utente=s["u"], testo="**forte** <script>alert(1)</script>")
    eventi, finito = flusso._passo(t.pk, flusso._Stato())
    voci = dict(_eventi(eventi))
    assert not finito and "<strong>forte</strong>" in voci["html"]["html"] and "<script>" not in voci["html"]["html"]
    assert "&lt;script&gt;" in voci["html"]["html"]


def test_il_testo_formattato_non_si_rispedisce_uguale(s):
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    t = Turno.objects.create(conversazione=c, utente=s["u"], testo="ciao")
    stato = flusso._Stato()
    flusso._passo(t.pk, stato)
    stato.ultimo_reso = 0
    assert "html" not in dict(_eventi(flusso._passo(t.pk, stato)[0]))


@pytest.mark.parametrize("testo", ["```python\nprint('<b>')\n```", "```\n<img src=x onerror=alert(1)>\n```", "```python\"><script>\nx\n```", "```pythonx\n<b>\n```"])
def test_il_codice_resta_sicuro(testo):
    html = str(markdown.rendi(testo))
    assert "<b>" not in html and "<script>" not in html and "<img" not in html


def test_il_codice_si_colora_col_nome_della_lingua():
    pytest.importorskip("pygments")
    html = str(markdown.rendi("```python\ndef f(): pass\n```"))
    assert 'data-lingua="python"' in html and '<span class="k">def</span>' in html


def test_codice_non_chiuso_mentre_arriva():
    assert "<pre" in str(markdown.rendi("```python\ndef f("))


# --- regressioni trovate provando la chat nel browser ---

def test_il_turno_del_titolo_non_blocca_il_messaggio_dopo(s):
    """Scrivendo mentre si genera il titolo, il messaggio andava perso senza avvisi."""
    c = _chat(s)
    Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], compito="titoli", battito="2099-01-01T00:00:00Z")
    t = motore.avvia(c, "Seconda domanda", s["u"], s["az"], sincrono=True)
    assert t.compito == "chat" and c.messaggi.filter(testo="Seconda domanda", ruolo="utente").exists()
    assert c.messaggi.filter(ruolo="assistente").count() == 2


def test_la_pagina_non_mostra_il_turno_del_titolo_come_risposta_in_corso(client, s):
    c = _chat(s)
    Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], compito="titoli", battito="2099-01-01T00:00:00Z")
    assert "data-flusso" not in client.get(reverse("ai:conversazione", args=[c.pk])).content.decode()


def test_il_flusso_mostra_la_risposta_del_suo_turno(s):
    c = _chat(s, ["Prima"])
    vecchia = c.messaggi.filter(ruolo="assistente").get()
    t = Turno.objects.create(conversazione=c, utente=s["u"], azienda=s["az"], stato=Turno.ERRORE, testo="")
    voci = dict(_eventi(flusso._passo(t.pk, flusso._Stato())[0]))
    assert voci["fine"]["html"] == "" and vecchia.testo
    MessaggioChat.objects.create(conversazione=c, ruolo="assistente", testo="Sua", turno=t)
    assert "Sua" in dict(_eventi(flusso._passo(t.pk, flusso._Stato())[0]))["fine"]["html"]


def test_il_titolo_automatico_non_sovrascrive_quello_scelto(s, monkeypatch):
    from ai.gateway.tipi import Testo
    from ai.motore import titoli
    c = Conversazione.objects.create(utente=s["u"], titolo="x")
    MessaggioChat.objects.create(conversazione=c, ruolo="utente", testo="d")
    MessaggioChat.objects.create(conversazione=c, ruolo="assistente", testo="r")

    def lento(*a, **k):                                  # l'utente rinomina mentre il modello scrive il titolo
        Conversazione.objects.filter(pk=c.pk).update(titolo="Scelto da me", titolo_generato=True)
        yield Testo("Automatico")
    monkeypatch.setattr(titoli, "gateway", lento)
    titoli.genera(c, s["u"], s["az"])
    c.refresh_from_db()
    assert c.titolo == "Scelto da me"
