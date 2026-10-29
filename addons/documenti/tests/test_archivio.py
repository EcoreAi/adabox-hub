import io
import zipfile

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Azienda
from documenti import accesso, hooks, servizi
from documenti.models import Cartella, Documento, Tag

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    azienda = Azienda.objects.get(pk=1)
    utenti = Group.objects.create(name="Utenti documenti")
    utenti.permissions.set(Permission.objects.filter(content_type__app_label="documenti").exclude(
        codename__in=["vedi_tutte_cartelle", "add_cartella", "delete_documento"]))
    capi = Group.objects.create(name="Capi")
    mario = User.objects.create_user("mario", password="x")
    mario.groups.add(utenti)
    pubblica = Cartella.objects.create(azienda=azienda, nome="Pubblica")
    sotto = Cartella.objects.create(azienda=azienda, nome="Sotto", padre=pubblica)
    riservata = Cartella.objects.create(azienda=azienda, nome="Riservata")
    riservata.gruppi_lettura.add(capi)
    figlia_riservata = Cartella.objects.create(azienda=azienda, nome="Figlia", padre=riservata)
    sola_lettura = Cartella.objects.create(azienda=azienda, nome="Archivio storico")
    sola_lettura.gruppi_lettura.add(utenti)
    sola_lettura.gruppi_scrittura.add(capi)
    return {"azienda": azienda, "mario": mario, "capi": capi, "pubblica": pubblica, "sotto": sotto,
            "riservata": riservata, "figlia": figlia_riservata, "storico": sola_lettura}


def _doc(cartella, nome="nota.txt", testo=b"ciao"):
    return servizi.carica(cartella, ContentFile(testo, name=nome))


def test_permessi_ereditati(scena):
    mario = scena["mario"]
    visibili = {c.nome for c in accesso.visibili(mario, scena["azienda"])}
    assert visibili == {"Pubblica", "Sotto", "Archivio storico"}            # la figlia eredita il limite
    scrivibili = {c.nome for c in accesso.scrivibili(mario, scena["azienda"])}
    assert scrivibili == {"Pubblica", "Sotto"}
    mario.groups.add(scena["capi"])
    del mario._gruppi_documenti
    assert {c.nome for c in accesso.scrivibili(mario, scena["azienda"])} >= {"Riservata", "Figlia", "Archivio storico"}


def test_archivio_mostra_solo_il_visibile(client, scena):
    _doc(scena["pubblica"], "pubblico.txt")
    _doc(scena["figlia"], "segreto.txt")
    client.force_login(scena["mario"])
    html = client.get("/documenti/").content.decode()
    assert "pubblico.txt" in html and "segreto.txt" not in html and "Riservata" not in html
    segreto = Documento.objects.get(nome="segreto.txt")
    assert client.get(f"/documenti/{segreto.pk}/scarica/").status_code == 404
    assert client.get(f"/documenti/{segreto.pk}/anteprima/").status_code == 404
    assert client.get(f"/documenti/documenti/{segreto.pk}/").status_code == 404


def test_caricamento_multiplo_e_regole(client, scena):
    client.force_login(scena["mario"])
    r = client.post("/documenti/carica/", {"cartella": scena["sotto"].pk, "file": [
        SimpleUploadedFile("foto.png", PNG, "image/png"), SimpleUploadedFile("virus.exe", b"MZ"),
        SimpleUploadedFile("a.txt", b"uno")]}, follow=True)
    html = r.content.decode()
    assert "Documenti caricati: 2" in html and "non ammessi" in html
    foto = Documento.objects.get(nome="foto.png")
    assert foto.mime == "image/png" and foto.proprietario == scena["mario"] and foto.cartella == scena["sotto"]
    r = client.post("/documenti/carica/", {"cartella": scena["storico"].pk, "file": SimpleUploadedFile("b.txt", b"x")})
    assert r.status_code == 403
    r = client.post("/documenti/carica/", {"cartella": scena["sotto"].pk, "file": SimpleUploadedFile("c.exe", b"x")},
                    HTTP_ACCEPT="application/json")
    assert r.status_code == 400 and r.json()["errori"]


def test_anteprima_e_download(client, scena):
    foto = servizi.carica(scena["pubblica"], SimpleUploadedFile("foto.png", PNG, "image/png"))
    client.force_login(scena["mario"])
    html = client.get(f"/documenti/{foto.pk}/anteprima/").content.decode()
    assert f"/documenti/{foto.pk}/scarica/?inline=1" in html and 'name="nome"' in html
    r = client.get(f"/documenti/{foto.pk}/scarica/?inline=1")
    assert r["Content-Type"] == "image/png" and "inline" in r["Content-Disposition"]
    assert b"".join(r.streaming_content) == PNG
    r = client.get(f"/documenti/{foto.pk}/scarica/")
    assert "attachment" in r["Content-Disposition"]


def test_azioni_di_massa(client, scena):
    a, b = _doc(scena["pubblica"], "a.txt", b"AAA"), _doc(scena["sotto"], "a.txt", b"BBB")     # altra cartella: niente versione
    storico = _doc(scena["storico"], "vecchio.txt")
    client.force_login(scena["mario"])
    r = client.post("/documenti/azione/", {"azione": "zip", "pk": [a.pk, b.pk]})
    archivio = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(archivio.namelist()) == ["a (1).txt", "a.txt"]
    assert {archivio.read(n) for n in archivio.namelist()} == {b"AAA", b"BBB"}
    client.post("/documenti/azione/", {"azione": "sposta", "pk": [a.pk], "cartella": scena["sotto"].pk})
    a.refresh_from_db()
    assert a.cartella == scena["sotto"]
    tag = Tag.objects.create(nome="Urgente")
    client.post("/documenti/azione/", {"azione": "tag", "pk": [a.pk, storico.pk], "tag": tag.pk})
    assert list(a.tag.all()) == [tag] and not storico.tag.exists()        # sola lettura: escluso
    client.post("/documenti/azione/", {"azione": "cestina", "pk": [a.pk]})
    a.refresh_from_db()
    assert a.cestinato_il is not None
    assert "a.txt" in client.get("/documenti/?cartella=cestino").content.decode()
    client.post("/documenti/azione/", {"azione": "ripristina", "pk": [a.pk]})
    a.refresh_from_db()
    assert a.cestinato_il is None
    assert client.post("/documenti/azione/", {"azione": "sposta", "pk": [a.pk],
                                              "cartella": scena["storico"].pk}).status_code == 403


def test_elimina_definitiva_solo_dal_cestino(client, superuser, scena):
    d = _doc(scena["pubblica"])
    percorso = d.file.path
    client.post("/documenti/azione/", {"azione": "elimina", "pk": [d.pk]})
    assert Documento.objects.filter(pk=d.pk).exists()
    servizi.cestina([d])
    client.post("/documenti/azione/", {"azione": "elimina", "pk": [d.pk]})
    import os
    assert not Documento.objects.filter(pk=d.pk).exists() and not os.path.exists(percorso)


def test_modifica_e_blocco(client, scena):
    d = _doc(scena["pubblica"])
    client.force_login(scena["mario"])
    tag = Tag.objects.create(nome="Contratto")
    client.post(f"/documenti/{d.pk}/aggiorna/", {"nome": "Contratto.txt", "descrizione": "firmato", "tag": [tag.pk]})
    d.refresh_from_db()
    assert d.nome == "Contratto.txt" and d.descrizione == "firmato" and list(d.tag.all()) == [tag]
    client.post(f"/documenti/documenti/{d.pk}/bottone/blocca/")
    d.refresh_from_db()
    assert d.bloccato_da == scena["mario"]
    altro = User.objects.create_user("luigi", password="x")
    altro.groups.set(scena["mario"].groups.all())
    client.force_login(altro)
    assert client.post(f"/documenti/{d.pk}/aggiorna/", {"nome": "X"}).status_code == 403


def test_nuova_cartella(client, scena):
    client.force_login(scena["mario"])
    client.post("/documenti/cartella/", {"nome": "Preventivi", "padre": scena["pubblica"].pk})
    assert Cartella.objects.filter(nome="Preventivi", padre=scena["pubblica"]).exists()
    assert client.post("/documenti/cartella/", {"nome": "In cima"}).status_code == 403
    assert client.post("/documenti/cartella/", {"nome": "No", "padre": scena["storico"].pk}).status_code == 403


def test_scheda_con_anteprima_e_chatter(client, superuser, scena):
    d = servizi.carica(scena["pubblica"], SimpleUploadedFile("foto.png", PNG, "image/png"))
    html = client.get(f"/documenti/documenti/{d.pk}/").content.decode()
    assert f"/documenti/{d.pk}/scarica/?inline=1" in html and "Anteprima" in html


def test_dashboard_e_demo(rf, superuser, settings, tmp_path):
    from pathlib import Path

    from django.core.management import call_command

    import documenti
    from documenti.dashboard import kpi
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    call_command("loaddata", str(Path(documenti.__file__).parent / "data" / "tag.json"), verbosity=0)
    Group.objects.create(name="Documenti / Responsabile")
    hooks.demo(None)
    hooks.demo(None)
    assert Documento.objects.filter(nome="Contratto quadro cliente.txt", tag__nome="Contratto").exists()
    richiesta = rf.get("/")
    richiesta.user, richiesta.azienda = superuser, Azienda.objects.get(pk=1)
    assert kpi(richiesta)["kpi"][0]["valore"] == 5
