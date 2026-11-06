"""Progetto collegato a una cartella dei Documenti: scelta tra quelle visibili, file letti da Ada, caricamento di una
cartella intera, «Salva nei Documenti» per documenti, grafici e tabelle. Sempre con i permessi di Documenti."""
from django.contrib.auth.models import Group, Permission, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from ai import archivio, contesto_utente, documenti_chat
from core import report
from ai.models import Artifact, Conversazione, ProgettoChat
from ai.tests.test_chat_gruppo2 import s  # noqa: F401  (fixture)
from documenti.models import Cartella, Documento

import pytest


@pytest.fixture
def d(s):
    s["u"].user_permissions.add(*Permission.objects.filter(content_type__app_label="documenti", codename__in=[
        "view_documento", "add_documento", "change_documento"]))
    u = User.objects.get(pk=s["u"].pk)
    aperta = Cartella.objects.create(azienda=s["az"], nome="AdaV3")
    sotto = Cartella.objects.create(azienda=s["az"], nome="Specifiche", padre=aperta)
    riservata = Cartella.objects.create(azienda=s["az"], nome="Direzione")
    riservata.gruppi_lettura.add(Group.objects.create(name="direzione"))
    progetto = ProgettoChat.objects.create(utente=u, azienda=s["az"], nome="Sviluppo", cartella_documenti=aperta.pk)
    return {**s, "u": u, "aperta": aperta, "sotto": sotto, "riservata": riservata, "progetto": progetto}


def _doc(cartella, nome):
    return Documento.objects.create(azienda=cartella.azienda, cartella=cartella, nome=nome,
                                    file=SimpleUploadedFile(nome, b"contenuto di prova"), dimensione=18)


def test_form_solo_cartelle_visibili(client, d):
    client.force_login(d["u"])
    pagina = client.get(reverse("ai:progetti_modifica", args=[d["progetto"].pk])).content.decode()
    assert "AdaV3 / Specifiche" in pagina and "Direzione" not in pagina
    r = client.post(reverse("ai:progetti_modifica", args=[d["progetto"].pk]), {"nome": "Sviluppo", "istruzioni": "", "cartella_documenti": d["riservata"].pk})
    assert r.status_code == 200                                                    # scelta non valida
    client.post(reverse("ai:progetti_modifica", args=[d["progetto"].pk]), {"nome": "Sviluppo", "istruzioni": "", "cartella_documenti": d["sotto"].pk})
    d["progetto"].refresh_from_db()
    assert d["progetto"].cartella_documenti == d["sotto"].pk


def test_ada_riceve_i_documenti_della_cartella(d):
    _doc(d["aperta"], "Roadmap.pdf")
    _doc(d["sotto"], "Voce.docx")
    _doc(d["riservata"], "Bilancio.xlsx")
    c = Conversazione.objects.create(utente=d["u"], titolo="x", progetto=d["progetto"])
    nota = contesto_utente.nota_progetto(c)
    assert "«AdaV3»" in nota and "Roadmap.pdf" in nota and "Voce.docx" in nota and "in Specifiche" in nota and "leggi_documento" in nota
    assert "Bilancio" not in nota


def test_albero_con_la_cartella(client, d):
    _doc(d["sotto"], "Voce.docx")
    client.force_login(d["u"])
    html = client.get(reverse("ai:albero_progetto", args=[d["progetto"].pk])).content.decode()
    file = html.split('data-gruppo="file"')[1]
    assert "Voce.docx" in file and "Specifiche" in file and 'data-carica-albero="cartella"' in file and "in AdaV3" in file
    assert "/elimina/archivio/" in file
    assert 'id="ai-salva-doc"' in client.get(reverse("ai:progetto", args=[d["progetto"].pk])).content.decode()


def test_cestino_dei_documenti_dall_albero(client, d):
    doc = _doc(d["aperta"], "Vecchio.pdf")
    client.force_login(d["u"])
    assert client.post(reverse("ai:elimina_elemento", args=["archivio", doc.pk])).json() == {"ok": True}
    doc.refresh_from_db()
    assert doc.cestinato_il is not None                                            # nel cestino, recuperabile
    riservato = _doc(d["riservata"], "Bilancio.xlsx")
    assert client.post(reverse("ai:elimina_elemento", args=["archivio", riservato.pk])).status_code == 404
    riservato.refresh_from_db()
    assert riservato.cestinato_il is None


def test_carica_una_cartella_intera(client, d):
    client.force_login(d["u"])
    file = [SimpleUploadedFile("a.txt", b"uno"), SimpleUploadedFile("b.txt", b"due"), SimpleUploadedFile("c.txt", b"tre")]
    r = client.post(reverse("ai:carica_archivio", args=[d["progetto"].pk]),
                    {"file": file, "percorso": ["Progetto/a.txt", "Progetto/Note/b.txt", "Progetto/Note/2026/c.txt"]})
    assert r.json() == {"caricati": 3, "errori": []}
    note = Cartella.objects.get(nome="Note", padre=d["aperta"])
    assert Documento.objects.filter(cartella=d["aperta"], nome="a.txt").exists()
    assert Documento.objects.filter(cartella=note, nome="b.txt").exists()
    assert Documento.objects.filter(cartella__nome="2026", cartella__padre=note, nome="c.txt").exists()


def test_senza_permesso_di_scrittura_non_carica(client, d):
    d["u"].user_permissions.remove(Permission.objects.get(codename="add_documento", content_type__app_label="documenti"))
    client.force_login(User.objects.get(pk=d["u"].pk))
    r = client.post(reverse("ai:carica_archivio", args=[d["progetto"].pk]), {"file": [SimpleUploadedFile("a.txt", b"x")], "percorso": ["a.txt"]})
    assert r.status_code == 403 and not Documento.objects.exists()


def test_salva_nei_documenti(client, d):
    client.force_login(d["u"])
    c = Conversazione.objects.create(utente=d["u"], titolo="x", progetto=d["progetto"])
    doc = documenti_chat.crea(c, d["u"], d["az"], "Note di rilascio", "# Note\\n- uno")
    url = reverse("ai:salva_documenti", args=["documento", doc.pk])
    r = client.post(url, {"cartella": d["aperta"].pk}).json()
    salvato = Documento.objects.get(nome="Note di rilascio.docx")
    assert salvato.cartella == d["aperta"] and "AdaV3" in r["messaggio"] and r["url"]
    client.post(url, {"cartella": d["aperta"].pk})
    salvato.refresh_from_db()
    assert salvato.versione == 2 and Documento.objects.filter(nome="Note di rilascio.docx").count() == 1   # versione nuova
    assert client.post(url, {"cartella": d["riservata"].pk}).status_code == 403
    tabella = Artifact.objects.create(conversazione=c, utente=d["u"], azienda=d["az"], tipo="tabella", titolo="Ticket",
                                      dati={"colonne": ["Nome"], "righe": [["Uno"]]}, spec={"tipo": "tabella", "vista": "inesistente"})
    r = client.post(reverse("ai:salva_documenti", args=["artifact", tabella.pk]), {"cartella": d["sotto"].pk})
    assert Documento.objects.get(nome="Ticket.csv").cartella == d["sotto"]
    altro = User.objects.create_user("bruno", password="x")
    altro.user_permissions.set(Permission.objects.filter(content_type__app_label__in=["ai", "documenti"]))
    client.force_login(altro)
    assert client.post(url, {"cartella": d["aperta"].pk}).status_code == 404


def test_senza_documenti_niente_cartella(client, s, settings):
    settings.ADDONS_ATTIVI = [m for m in settings.ADDONS_ATTIVI if m != "documenti"]
    assert not archivio.attivo() and archivio.cartelle(s["u"], s["az"]) == []
    pagina = client.get(reverse("ai:progetti_nuovo")).content.decode()
    assert "cartella_documenti" not in pagina


def _grafico(d):
    c = Conversazione.objects.create(utente=d["u"], titolo="x", progetto=d["progetto"])
    return Artifact.objects.create(conversazione=c, utente=d["u"], azienda=d["az"], tipo="grafico", titolo="Per stato",
                                   dati={"serie": [["Aperto", 3], ["Chiuso", 5]], "totale": 8}, spec={"tipo": "grafico", "grafico": "barre", "vista": "inesistente"})


@pytest.mark.pdf
@pytest.mark.skipif(not report.disponibile(), reason="WeasyPrint senza Pango: deploy/test-pdf.sh")
def test_grafico_salvato_in_pdf(client, d):
    client.force_login(d["u"])
    client.post(reverse("ai:salva_documenti", args=["artifact", _grafico(d).pk]), {"cartella": d["aperta"].pk})
    assert Documento.objects.get(nome="Per stato.pdf").file.read()[:5] == b"%PDF-"


def test_grafico_senza_pdf_lo_dice(client, d, monkeypatch):
    def manca():
        raise report.ReportNonDisponibile("La generazione dei PDF non è disponibile su questo server (manca Pango).")
    monkeypatch.setattr(report, "weasyprint", manca)
    client.force_login(d["u"])
    r = client.post(reverse("ai:salva_documenti", args=["artifact", _grafico(d).pk]), {"cartella": d["aperta"].pk})
    assert r.status_code == 503 and "Pango" in r.json()["errore"] and not Documento.objects.exists()
