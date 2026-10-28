import datetime

import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core import allegati
from core.models import AttivitaPianificata, Azienda
from documenti import condivisioni, servizi
from documenti.models import AccessoCondivisione, Cartella, Condivisione, Documento, Richiesta

OGGI = timezone.localdate()


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    cache.clear()
    azienda = Azienda.objects.get(pk=1)
    cartella = Cartella.objects.create(azienda=azienda, nome="Per il notaio")
    altra = Cartella.objects.create(azienda=azienda, nome="Interna")
    a = servizi.carica(cartella, ContentFile(b"atto", name="atto.txt"))
    b = servizi.carica(altra, ContentFile(b"interno", name="interno.txt"))
    return azienda, cartella, altra, a, b


def test_crea_condivisione_dal_form(client, superuser, scena):
    azienda, cartella, _, a, _ = scena
    assert "scadenza" in client.get("/documenti/condivisioni/nuovo/").content.decode()
    r = client.post("/documenti/condivisioni/nuovo/", {"nome": "Notaio", "scadenza": (OGGI + datetime.timedelta(days=5)).isoformat(),
                                                       "cartella": cartella.pk, "consente_caricamento": "on"})
    c = Condivisione.objects.get()
    assert r.status_code == 302 and c.creata_da == superuser and len(c.token) >= 30
    html = client.get(f"/documenti/condivisioni/{c.pk}/").content.decode()
    assert f"/documenti/condivisi/{c.token}/" in html
    r = client.post("/documenti/condivisioni/nuovo/", {"nome": "Vuota", "scadenza": OGGI.isoformat()})
    assert r.status_code == 200 and "almeno un documento" in r.content.decode()


def test_pagina_pubblica(client, scena):
    azienda, cartella, _, a, b = scena
    c = Condivisione.objects.create(azienda=azienda, nome="Notaio", cartella=cartella, scadenza=OGGI)
    c.documenti.add(b)
    html = client.get(f"/documenti/condivisi/{c.token}/").content.decode()
    assert "atto.txt" in html and "interno.txt" in html and "Invia dei file" not in html
    r = client.get(f"/documenti/condivisi/{c.token}/{a.pk}/")
    assert r.status_code == 200 and b"".join(r.streaming_content) == b"atto"
    estraneo = servizi.carica(cartella.__class__.objects.create(azienda=azienda, nome="Altro"),
                              ContentFile(b"x", name="x.txt"))
    assert client.get(f"/documenti/condivisi/{c.token}/{estraneo.pk}/").status_code == 404
    assert client.get("/documenti/condivisi/token-falso/").status_code == 404
    assert list(AccessoCondivisione.objects.order_by("pk").values_list("azione", flat=True)) == ["visita", "download"]
    servizi.cestina([a])
    assert "atto.txt" not in client.get(f"/documenti/condivisi/{c.token}/").content.decode()


def test_scaduta_e_revocata(client, superuser, scena):
    azienda, cartella, _, a, _ = scena
    c = Condivisione.objects.create(azienda=azienda, nome="X", cartella=cartella, scadenza=OGGI - datetime.timedelta(days=1))
    client.logout()
    assert client.get(f"/documenti/condivisi/{c.token}/").status_code == 410
    c.scadenza = OGGI
    c.save()
    client.force_login(superuser)
    client.post(f"/documenti/condivisioni/{c.pk}/bottone/revoca/")
    client.logout()
    r = client.get(f"/documenti/condivisi/{c.token}/{a.pk}/")
    assert r.status_code == 410 and "non è più valido" in r.content.decode()


def test_caricamento_dal_link(client, scena):
    azienda, cartella, _, _, _ = scena
    c = Condivisione.objects.create(azienda=azienda, nome="Raccolta", cartella=cartella, scadenza=OGGI,
                                    consente_caricamento=True)
    r = client.post(f"/documenti/condivisi/{c.token}/", {"file": [SimpleUploadedFile("Carta identità.pdf", b"%PDF-1"),
                                                                 SimpleUploadedFile("x.exe", b"MZ")]})
    assert "File ricevuti: 1" in r.content.decode() and "non ammessi" in r.content.decode()
    d = Documento.objects.get(nome="Carta identità.pdf")
    assert d.cartella == cartella and d.proprietario is None and "Raccolta" in d.descrizione


def test_limite_di_frequenza(client, scena, monkeypatch):
    azienda, cartella, _, _, _ = scena
    monkeypatch.setattr(condivisioni, "RICHIESTE_AL_MINUTO", 3)
    c = Condivisione.objects.create(azienda=azienda, nome="X", cartella=cartella, scadenza=OGGI)
    codici = [client.get(f"/documenti/condivisi/{c.token}/").status_code for _ in range(4)]
    assert codici == [200, 200, 200, 429]


def test_condividi_dalla_selezione(client, superuser, scena):
    _, _, _, a, b = scena
    r = client.post("/documenti/azione/", {"azione": "condividi", "pk": [a.pk, b.pk]})
    c = Condivisione.objects.get()
    assert r["Location"].endswith(f"/documenti/condivisioni/{c.pk}/") and c.documenti.count() == 2
    assert c.scadenza == OGGI + datetime.timedelta(days=30)


def test_richiesta_attivita_ed_evasione(client, superuser, scena):
    azienda, cartella, _, _, _ = scena
    luca = User.objects.create_user("luca", password="x")
    client.post("/documenti/richieste/nuovo/", {"titolo": "Visura camerale", "destinatario": luca.pk,
                                                "scadenza": OGGI.isoformat(), "cartella": cartella.pk})
    richiesta = Richiesta.objects.get()
    assert richiesta.richiesta_da == superuser and richiesta.stato == "aperta"
    attivita = AttivitaPianificata.objects.get()
    assert attivita.assegnatario == luca and "Visura" in attivita.riepilogo
    client.force_login(luca)                     # luca non ha permessi sui documenti: la richiesta basta
    assert "Carica e chiudi" in client.get(f"/documenti/richieste/{richiesta.pk}/").content.decode()
    r = client.post(f"/documenti/richiesta/{richiesta.pk}/carica/", {"file": SimpleUploadedFile("visura.pdf", b"%PDF")})
    assert r.status_code == 302
    richiesta.refresh_from_db()
    assert richiesta.stato == "completata" and richiesta.documento.cartella == cartella
    assert not AttivitaPianificata.objects.exists()
    assert client.post(f"/documenti/richiesta/{richiesta.pk}/carica/",
                       {"file": SimpleUploadedFile("b.pdf", b"%PDF")}).status_code == 404


def test_annulla_richiesta(client, superuser, scena):
    azienda, cartella, _, _, _ = scena
    luca = User.objects.create_user("luca", password="x")
    client.post("/documenti/richieste/nuovo/", {"titolo": "Durc", "destinatario": luca.pk,
                                                "scadenza": OGGI.isoformat(), "cartella": cartella.pk})
    richiesta = Richiesta.objects.get()
    client.post(f"/documenti/richieste/{richiesta.pk}/bottone/annulla/")
    richiesta.refresh_from_db()
    assert richiesta.stato == "annullata" and not AttivitaPianificata.objects.exists()


def test_cartella_collegata_raccoglie_gli_allegati(client, superuser, scena):
    azienda, _, _, _, _ = scena
    allegati.salva(azienda, ContentFile(b"vecchio", name="prima.txt"), superuser)
    tipo = ContentType.objects.get_for_model(Azienda)
    r = client.post("/documenti/cartelle/nuovo/", {"nome": "Allegati aziende", "modello": tipo.pk})
    cartella = Cartella.objects.get(nome="Allegati aziende")
    assert r.status_code == 302 and cartella.documenti.get().nome == "prima.txt"     # quelli già caricati
    allegato = allegati.salva(azienda, ContentFile(b"nuovo", name="dopo.txt"), superuser)
    d = Documento.objects.get(allegato=allegato)
    assert d.cartella == cartella and d.record == azienda and d.proprietario == superuser
    r = client.get(f"/documenti/{d.pk}/scarica/")
    assert b"".join(r.streaming_content) == b"nuovo"
    html = client.get(f"/core/aziende/{azienda.pk}/").content.decode()
    assert "Documenti" in html and "dopo.txt" in html
    r = client.post("/documenti/cartelle/nuovo/", {"nome": "Doppione", "modello": tipo.pk})
    assert r.status_code == 200 and "già gli allegati" in r.content.decode()
    allegato.delete()
    assert not Documento.objects.filter(pk=d.pk).exists()
