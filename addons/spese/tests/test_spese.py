import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

import personale
import spese
from core.models import Azienda
from personale.models import Dipendente
from spese import flusso, hooks
from spese.models import CategoriaSpesa, NotaSpese, RigaSpesa

OGGI = timezone.localdate()


def _utente(nome, *extra):
    u = User.objects.create_user(nome, f"{nome}@example.com", "x")
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="spese").filter(
        codename__in=["view_notaspese", "add_notaspese", "change_notaspese", "delete_notaspese", "view_rigaspesa",
                      "add_rigaspesa", "change_rigaspesa", "delete_rigaspesa", "view_categoriaspesa", *extra]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def scena(db, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    for app, file in ((spese, "categorie.json"), (personale, "tipi.json")):
        call_command("loaddata", str(Path(app.__file__).parent / "data" / file), verbosity=0)
    azienda = Azienda.objects.get(pk=1)
    capo_u, mario_u, hr_u = _utente("capo"), _utente("mario"), _utente("hr", "vedi_tutte_note")
    capo = Dipendente.objects.create(azienda=azienda, nome="Laura", cognome="Ferri", utente=capo_u)
    mario = Dipendente.objects.create(azienda=azienda, nome="Mario", cognome="Rossi", utente=mario_u, responsabile=capo)
    return {"azienda": azienda, "capo_u": capo_u, "mario_u": mario_u, "hr_u": hr_u, "mario": mario,
            "vitto": CategoriaSpesa.objects.get(nome="Vitto"), "km": CategoriaSpesa.objects.get(chilometrica=True),
            "altro": CategoriaSpesa.objects.get(nome="Altro")}


def _form(righe, **extra):
    dati = {"titolo": "Trasferta Milano", "righe0-TOTAL_FORMS": str(len(righe)), "righe0-INITIAL_FORMS": "0",
            "righe0-MIN_NUM_FORMS": "0", "righe0-MAX_NUM_FORMS": "1000", **extra}
    for i, r in enumerate(righe):
        dati.update({f"righe0-{i}-{k}": v for k, v in {"data": OGGI.isoformat(), **r}.items()})
    return dati


def test_dipendente_crea_la_nota_con_ricevute(client, scena):
    client.force_login(scena["mario_u"])
    html = client.get("/spese/note/nuovo/").content.decode()
    assert 'enctype="multipart/form-data"' in html and 'name="dipendente"' not in html
    r = client.post("/spese/note/nuovo/", _form([
        {"categoria": scena["vitto"].pk, "descrizione": "Pranzo", "importo": "25.50",
         "ricevuta": SimpleUploadedFile("scontrino.pdf", b"%PDF-1.4")},
        {"categoria": scena["km"].pk, "descrizione": "Milano A/R", "km": "100"}]))
    nota = NotaSpese.objects.get()
    assert r.status_code == 302 and nota.dipendente == scena["mario"] and nota.numero.startswith("NS/")
    assert nota.totale == Decimal("67.50")                                    # 25,50 + 100 km × 0,42
    pranzo = nota.righe.get(descrizione="Pranzo")
    assert pranzo.ricevuta.name.endswith("scontrino.pdf")
    dettaglio = client.get(f"/spese/note/{nota.pk}/").content.decode()
    assert "scontrino.pdf" in dettaglio and f"/spese/ricevuta/{pranzo.pk}/" in dettaglio
    assert "spese/20" not in dettaglio                                         # niente percorsi interni
    assert client.get(f"/spese/ricevuta/{pranzo.pk}/").status_code == 200


def test_limiti_e_controlli(client, scena):
    client.force_login(scena["mario_u"])
    r = client.post("/spese/note/nuovo/", _form([{"categoria": scena["vitto"].pk, "descrizione": "Cena",
                                                  "importo": "90"}]))
    assert r.status_code == 200 and "Oltre il limite" in r.content.decode() and not NotaSpese.objects.exists()
    nota = NotaSpese.objects.create(azienda=scena["azienda"], dipendente=scena["mario"], titolo="X")
    RigaSpesa.objects.create(nota=nota, categoria=scena["altro"], descrizione="Cancelleria", importo=Decimal(10))
    with pytest.raises(ValidationError, match="Manca la ricevuta"):
        flusso.invia(nota, scena["mario_u"])
    vuota = NotaSpese.objects.create(azienda=scena["azienda"], dipendente=scena["mario"], titolo="Y")
    with pytest.raises(ValidationError, match="non ha spese"):
        flusso.invia(vuota, scena["mario_u"])


def _nota_pronta(scena):
    nota = NotaSpese.objects.create(azienda=scena["azienda"], dipendente=scena["mario"], titolo="Trasferta")
    RigaSpesa.objects.create(nota=nota, categoria=scena["km"], descrizione="Cliente", km=Decimal(50))
    nota.ricalcola()
    return nota


def test_flusso_completo(client, scena):
    nota = _nota_pronta(scena)
    client.force_login(scena["mario_u"])
    client.post(f"/spese/note/{nota.pk}/bottone/invia/")
    nota.refresh_from_db()
    assert nota.stato == "inviata" and nota.totale == Decimal("21.00")
    assert client.get(f"/spese/note/{nota.pk}/modifica/").status_code == 403
    assert client.post(f"/spese/note/{nota.pk}/bottone/approva/").status_code == 403    # non si approva da sé
    client.force_login(scena["capo_u"])
    client.post(f"/spese/note/{nota.pk}/bottone/rifiuta/", {"nota": "Manca il motivo della trasferta"})
    nota.refresh_from_db()
    assert nota.stato == "rifiutata" and "motivo" in nota.nota_decisione
    client.force_login(scena["mario_u"])
    client.post(f"/spese/note/{nota.pk}/bottone/riapri/")
    client.post(f"/spese/note/{nota.pk}/bottone/invia/")
    client.force_login(scena["capo_u"])
    client.post(f"/spese/note/{nota.pk}/bottone/approva/")
    nota.refresh_from_db()
    assert nota.stato == "approvata" and nota.decisa_da == scena["capo_u"]
    with pytest.raises(PermissionDenied):
        flusso.rimborsa(nota, scena["capo_u"])                                 # rimborsa l'amministrazione
    client.force_login(scena["hr_u"])
    client.post("/spese/note/azione/rimborsa_selezionate/", {"pk": [nota.pk]})
    nota.refresh_from_db()
    assert nota.stato == "rimborsata" and nota.rimborsata_il == OGGI


def test_visibilita(client, scena):
    nota = _nota_pronta(scena)
    altro = _utente("altro")
    Dipendente.objects.create(azienda=scena["azienda"], nome="Altro", cognome="Collega", utente=altro)
    client.force_login(altro)
    assert client.get(f"/spese/note/{nota.pk}/").status_code == 404
    riga = nota.righe.first()
    assert client.get(f"/spese/ricevuta/{riga.pk}/").status_code == 404
    senza_scheda = _utente("esterno")
    client.force_login(senza_scheda)
    assert client.get("/spese/note/nuovo/").status_code == 403


def test_stampa_html(client, scena):
    from core import report
    from core.viste import registry
    nota = _nota_pronta(scena)
    richiesta = type("R", (), {"user": scena["hr_u"], "azienda": scena["azienda"]})()
    html = report.html(registry.per_modello(NotaSpese), richiesta, [nota], 0)
    assert "Rimborso chilometrico" in html and ("21,00" in html or "21.00" in html)


def test_demo_e_dashboard(rf, superuser, scena):
    from personale import hooks as hp
    from spese.dashboard import kpi
    Dipendente.objects.all().delete()
    Group.objects.create(name="Note spese / Dipendente")
    hp.demo(None)
    hooks.post_install(None)
    hooks.demo(None)
    hooks.demo(None)
    assert NotaSpese.objects.count() == 2 and NotaSpese.objects.get(stato="inviata").totale > 0
    richiesta = rf.get("/")
    richiesta.user, richiesta.azienda = superuser, scena["azienda"]
    assert kpi(richiesta)["kpi"][0]["valore"] == 1
