import io
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from PIL import Image

import fiscale
import prodotti
from core.models import Azienda
from prodotti import immagini
from prodotti.models import ImmagineProdotto, Prodotto


@pytest.fixture
def dati(db, tmp_path, settings):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app in (fiscale, prodotti):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / "iniziali.json"), verbosity=0)
    return Azienda.objects.get(pk=1)


def foto(nome="foto.jpg", formato="JPEG", lato=(3000, 2000), modo="RGB", exif=None):
    buf = io.BytesIO()
    img = Image.new(modo, lato, (200, 30, 30, 128) if modo == "RGBA" else (200, 30, 30))
    img.save(buf, formato, **({"exif": exif} if exif else {}))
    return SimpleUploadedFile(nome, buf.getvalue(), content_type=f"image/{formato.lower()}")


def test_ridotta_e_senza_exif(dati):
    exif = Image.Exif()
    exif[0x0112] = 6                  # ruotata di 90°: va raddrizzata
    exif[0x010F] = "Fotocamera"
    p = Prodotto.objects.create(azienda=dati, nome="Sedia", immagine=foto(exif=exif.tobytes()))
    assert p.immagine.name.startswith(f"prodotti/{dati.pk}/") and p.immagine.name.endswith(".jpg")
    with Image.open(immagini.storage.path(p.immagine.name)) as img:
        assert max(img.size) == immagini.LATO_MASSIMO and img.size[1] > img.size[0]      # raddrizzata
        assert not img.getexif()


def test_trasparenza_resta_png(dati):
    p = Prodotto.objects.create(azienda=dati, nome="Logo", immagine=foto("l.png", "PNG", (100, 100), "RGBA"))
    assert p.immagine.name.endswith(".png")


def test_file_non_immagine_rifiutato(dati):
    p = Prodotto(azienda=dati, nome="X", immagine=SimpleUploadedFile("x.jpg", b"non sono una foto"))
    with pytest.raises(ValidationError, match="immagine"):
        p.full_clean()


def test_sostituita_e_cancellata(dati, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        p = Prodotto.objects.create(azienda=dati, nome="Sedia", immagine=foto())
    vecchio = p.immagine.name
    with django_capture_on_commit_callbacks(execute=True):
        p.immagine = foto("nuova.jpg", lato=(50, 50))
        p.save()
    assert not immagini.storage.exists(vecchio) and immagini.storage.exists(p.immagine.name)
    nome = p.immagine.name
    with django_capture_on_commit_callbacks(execute=True):
        p.delete()
    assert not immagini.storage.exists(nome)


def test_principale_dalla_galleria(dati):
    p = Prodotto.objects.create(azienda=dati, nome="Tavolo")
    assert p.url_immagine == ""
    g = ImmagineProdotto.objects.create(prodotto=p, file=foto(), ordine=2)
    ImmagineProdotto.objects.create(prodotto=p, file=foto(), ordine=5)
    assert immagini.principale(p) == g.file.name


def test_carica_dal_form_e_vedi(client, superuser, dati):
    r = client.post("/prodotti/prodotti/nuovo/", {
        "nome": "Lampada", "tipo": "bene", "unita": 1, "prezzo_vendita": "25", "costo": "10", "aliquota_iva": 1,
        "scorta_minima": "0", "attivo": "on", "immagine": foto()})
    assert r.status_code == 302
    p = Prodotto.objects.get(nome="Lampada")
    assert p.immagine
    url = p.immagine.url
    assert url == f"/prodotti/immagine/{p.immagine.name}"
    r = client.get(url)
    assert r.status_code == 200 and r["Content-Type"] == "image/jpeg" and "private" in r["Cache-Control"]
    piccola = client.get(url + "?lato=200")
    with Image.open(io.BytesIO(b"".join(piccola.streaming_content))) as img:
        assert max(img.size) == 200
    assert client.get(url + "?lato=123").status_code == 404
    pagine = [client.get(f"/prodotti/prodotti/{p.pk}/").content.decode(), client.get("/prodotti/prodotti/").content.decode(),
              client.get(f"/prodotti/prodotti/{p.pk}/modifica/").content.decode()]
    assert all(p.immagine.name in pagina for pagina in pagine)


def test_galleria_dal_form(client, superuser, dati):
    p = Prodotto.objects.create(azienda=dati, nome="Divano")
    r = client.post(f"/prodotti/prodotti/{p.pk}/modifica/", {
        "nome": "Divano", "tipo": "bene", "unita": 1, "prezzo_vendita": "500", "costo": "0", "aliquota_iva": 1,
        "scorta_minima": "0", "attivo": "on",
        "righe0-TOTAL_FORMS": "1", "righe0-INITIAL_FORMS": "0", "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000",
        "righe0-0-file": foto(), "righe0-0-didascalia": "Di lato", "righe0-0-ordine": "1"})
    assert r.status_code == 302
    assert p.immagini.get().didascalia == "Di lato"
    assert client.get(p.immagini.get().file.url).status_code == 200


def test_immagine_solo_per_chi_vede_il_prodotto(client, dati, utente):
    altra = Azienda.objects.create(nome="Altra")
    p = Prodotto.objects.create(azienda=altra, nome="Segreto", immagine=foto())
    client.force_login(utente)
    assert client.get(p.immagine.url).status_code in (403, 404)
    utente.groups.add(Group.objects.get_or_create(name="Prodotti / Utente")[0])
    utente.user_permissions.add(*__import__("django.contrib.auth.models", fromlist=["Permission"]).Permission.objects
                                .filter(codename="view_prodotto"))
    utente = User.objects.get(pk=utente.pk)
    client.force_login(utente)
    assert client.get(p.immagine.url).status_code == 404               # altra azienda
    assert client.get("/prodotti/immagine/prodotti/1/../../segreto.jpg").status_code == 404
    client.logout()
    assert client.get(p.immagine.url).status_code == 302               # al login


def test_catalogo_html(client, superuser, dati):
    Prodotto.objects.create(azienda=dati, nome="Con foto", immagine=foto())
    Prodotto.objects.create(azienda=dati, nome="Senza foto")
    pks = list(Prodotto.objects.values_list("pk", flat=True))
    from prodotti import catalogo
    from django.test import RequestFactory
    richiesta = RequestFactory().get("/")
    richiesta.user, richiesta.azienda = superuser, dati
    html = catalogo.html(richiesta, Prodotto.objects.filter(pk__in=pks))
    assert "Con foto" in html and "Senza foto" in html and "file://" in html
    r = client.post("/prodotti/prodotti/azione/stampa_catalogo/", {"pk": pks})
    assert r.status_code in (200, 503)
