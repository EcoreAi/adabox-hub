"""Il documento accanto alla chat: Ada lo scrive e lo modifica, l'utente anche; versioni, conflitti, confini."""
import io

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from ai import documenti_chat, provenienza
from ai.models import Conversazione, DocumentoChat, Evento, MessaggioChat, Turno
from ai.strumenti import Contesto, disponibili
from ai.strumenti.registro import ErroreStrumento
from core.models import Azienda


def _utente(nome, azienda):
    u = User.objects.create_user(nome, password="x")
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="ai"))
    u.profilo.aziende.set([azienda])
    u.profilo.azienda_predefinita = azienda
    u.profilo.save()
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(db, client):
    a = Azienda.objects.first()
    u = _utente("anna", a)
    client.force_login(u)
    c = Conversazione.objects.create(utente=u, titolo="x")
    t = Turno.objects.create(conversazione=c, utente=u, azienda=a)
    return {"u": u, "az": a, "c": c, "t": t, "ctx": Contesto(utente=u, azienda=a, conversazione=c, turno=t)}


def _strumento(nome, u):
    return next(x for x in disponibili(u) if x.nome == nome)


def test_ada_scrive_legge_e_modifica(s):
    r = _strumento("scrivi_documento", s["u"]).funzione(s["ctx"], titolo="Offerta", testo="# Offerta\n\nPrezzo: 100 euro.\nValida 30 giorni.")
    d = DocumentoChat.objects.get(pk=r["documento"])
    assert d.versione == 1 and d.versioni.get().autore == "ada" and _strumento("scrivi_documento", s["u"]).rischio == "lettura"
    assert "Prezzo" in _strumento("leggi_documento_chat", s["u"]).funzione(s["ctx"], documento=d.pk)["testo"]
    modifica = _strumento("modifica_documento", s["u"]).funzione
    modifica(s["ctx"], documento=d.pk, modifiche=[{"cerca": "100 euro", "sostituisci": "120 euro"}])
    d.refresh_from_db()
    assert "120 euro" in d.testo and d.versione == 2
    with pytest.raises(ErroreStrumento, match="0 volte"):
        modifica(s["ctx"], documento=d.pk, modifiche=[{"cerca": "70 euro", "sostituisci": "x"}])
    with pytest.raises(ErroreStrumento, match="3 volte"):
        modifica(s["ctx"], documento=d.pk, modifiche=[{"cerca": "a", "sostituisci": "x"}])
    modifica(s["ctx"], documento=d.pk, testo="Tutto nuovo", titolo="Offerta 2")
    d.refresh_from_db()
    assert (d.testo, d.titolo, d.versione) == ("Tutto nuovo", "Offerta 2", 3)


def test_solo_i_documenti_di_questa_chat(s):
    d = documenti_chat.crea(s["c"], s["u"], s["az"], "A", "testo")
    altra = Conversazione.objects.create(utente=s["u"], titolo="y")
    with pytest.raises(ErroreStrumento, match="non trovato"):
        _strumento("leggi_documento_chat", s["u"]).funzione(Contesto(utente=s["u"], azienda=s["az"], conversazione=altra), documento=d.pk)


def test_editor_salva_conflitto_e_ripristino(s, client):
    d = documenti_chat.crea(s["c"], s["u"], s["az"], "Lettera", "Gentile cliente")
    r = client.get(f"{reverse('ai:conversazione', args=[s['c'].pk])}?documento={d.pk}")
    assert r.status_code == 200 and b'data-tela' in r.content and b'name="documento"' in r.content
    client.post(reverse("ai:salva_documento", args=[d.pk]), {"testo": "Gentile cliente,\r\nla ringrazio", "versione": 1}, HTTP_HX_REQUEST="true")
    d.refresh_from_db()
    assert d.testo == "Gentile cliente,\nla ringrazio" and d.versione == 2 and d.versioni.first().autore == "utente"
    r = client.post(reverse("ai:salva_documento", args=[d.pk]), {"testo": "vecchia copia", "versione": 1}, HTTP_HX_REQUEST="true")
    d.refresh_from_db()
    assert d.versione == 2 and "vecchia copia" in r.content.decode() and "è cambiato" in r.content.decode()
    client.post(reverse("ai:ripristina_documento", args=[d.pk, 1]), HTTP_HX_REQUEST="true")
    d.refresh_from_db()
    assert d.testo == "Gentile cliente" and d.versione == 3


def test_scarica_md_e_word(s, client):
    from docx import Document
    d = documenti_chat.crea(s["c"], s["u"], s["az"], "Verbale", "## Presenti\n- Anna **Rossi**\n1. Primo punto\nTesto")
    r = client.get(reverse("ai:scarica_documento", args=[d.pk, "md"]))
    assert r.content.decode().startswith("# Verbale") and "Verbale.md" in r["Content-Disposition"]
    r = client.get(reverse("ai:scarica_documento", args=[d.pk, "docx"]))
    testi = [p.text for p in Document(io.BytesIO(r.content)).paragraphs]
    assert testi == ["Verbale", "Presenti", "Anna Rossi", "Primo punto", "Testo"]
    assert client.get(reverse("ai:scarica_documento", args=[d.pk, "pdf"])).status_code == 404


def test_di_un_altro_utente_no(s, client):
    d = documenti_chat.crea(s["c"], s["u"], s["az"], "Mio", "segreto")
    client.force_login(_utente("bruno", s["az"]))
    assert client.get(reverse("ai:scarica_documento", args=[d.pk, "md"])).status_code == 404
    assert client.post(reverse("ai:salva_documento", args=[d.pk]), {"testo": "x", "versione": 1}).status_code == 404
    assert client.get(reverse("ai:documento", args=[d.pk]), HTTP_HX_REQUEST="true").status_code == 404
    d.refresh_from_db()
    assert d.testo == "segreto"


def test_scheda_sotto_la_risposta_stella_e_pannello(s, client):
    _strumento("scrivi_documento", s["u"]).funzione(s["ctx"], titolo="Procedura resi", testo="Passi")
    d = DocumentoChat.objects.get()
    MessaggioChat.objects.create(conversazione=s["c"], ruolo="assistente", testo="Ecco la procedura.", turno=s["t"])
    pagina = client.get(reverse("ai:conversazione", args=[s["c"].pk])).content.decode()
    assert f"?documento={d.pk}" in pagina and "Procedura resi" in pagina
    client.post(reverse("ai:stella_documento", args=[d.pk]), HTTP_HX_REQUEST="true")
    assert "Procedura resi" in client.get(reverse("ai:chat")).content.decode().split('data-contenuto="documenti"')[1]


def test_la_nota_dice_ad_ada_quale_documento_e_aperto(s, client, monkeypatch):
    from ai import motore
    d = documenti_chat.crea(s["c"], s["u"], s["az"], "Lettera", "x")
    visti = {}
    monkeypatch.setattr(motore, "avvia", lambda *a, **k: visti.update(k) or Turno.objects.create(conversazione=s["c"], utente=s["u"], azienda=s["az"]))
    client.post(reverse("ai:invia_conversazione", args=[s["c"].pk]), {"testo": "accorcia il secondo paragrafo", "documento": d.pk})
    assert f"documento n. {d.pk}" in visti["nota"]


def test_non_conta_come_dato_del_gestionale(s):
    Evento.objects.create(conversazione=s["c"], turno=s["t"], tipo=Evento.ASSISTENTE,
                          dati={"ruolo": "assistente", "blocchi": [{"tipo": "strumento", "id": "a", "nome": "leggi_documento_chat", "argomenti": {}}]})
    Evento.objects.create(conversazione=s["c"], turno=s["t"], tipo=Evento.STRUMENTO,
                          dati={"ruolo": "strumento", "risultati": [{"id": "a", "contenuto": "testo", "errore": False}]})
    pv = provenienza.calcola(s["t"], "Ho accorciato il documento.")
    assert pv["letture"] == 0 and pv["esito"] == "conversazione"
