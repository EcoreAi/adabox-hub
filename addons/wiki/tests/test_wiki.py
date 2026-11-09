"""Wiki: permessi per spazio (aperto, solo membri, chi scrive), versioni e ripristino, [[Titolo]] e citazioni, albero."""
import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError

from core.models import Azienda
from wiki import servizi
from wiki.models import MembroWiki, PaginaWiki, SpazioWiki


def _utente(nome):
    u = User.objects.create_user(nome, f"{nome}@x.it", "x")
    u.user_permissions.set(Permission.objects.filter(content_type__app_label="wiki", codename__in=[
        "view_spaziowiki", "view_paginawiki", "add_paginawiki", "change_paginawiki", "view_versionepagina"]))
    return User.objects.get(pk=u.pk)


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    anna, luca = _utente("anna"), _utente("luca")
    procedure = SpazioWiki.objects.create(azienda=azienda, nome="Procedure")
    MembroWiki.objects.create(spazio=procedure, utente=anna, ruolo="scrive")
    hr = SpazioWiki.objects.create(azienda=azienda, nome="HR", aperto=False)
    MembroWiki.objects.create(spazio=hr, utente=anna, ruolo="legge")
    ferie = PaginaWiki.objects.create(azienda=azienda, spazio=procedure, titolo="Ferie", testo="Chiedi dal **profilo**. Vedi [[Rimborsi]].")
    riservata = PaginaWiki.objects.create(azienda=azienda, spazio=hr, titolo="Stipendi")
    return {"azienda": azienda, "anna": anna, "luca": luca, "procedure": procedure, "hr": hr, "ferie": ferie, "riservata": riservata}


def test_permessi(client, s):
    client.force_login(s["luca"])
    html = client.get("/wiki/pagine/").content.decode()
    assert "Ferie" in html and "Stipendi" not in html
    assert client.get(f"/wiki/pagine/{s['riservata'].pk}/").status_code == 404
    assert client.get(f"/wiki/pagine/{s['ferie'].pk}/modifica/").status_code == 403       # legge, non scrive
    client.force_login(s["anna"])
    assert client.get(f"/wiki/pagine/{s['riservata'].pk}/").status_code == 200
    assert client.get(f"/wiki/pagine/{s['riservata'].pk}/modifica/").status_code == 403    # membro che legge


def test_versioni_collegamenti_albero(client, s):
    client.force_login(s["anna"])
    p = s["ferie"]
    for testo in ("Prima stesura", "Seconda stesura"):
        client.post(f"/wiki/pagine/{p.pk}/modifica/", {"titolo": "Ferie", "spazio": s["procedure"].pk, "ordine": 10, "testo": testo, "padre": ""})
    assert list(p.versioni.values_list("numero", flat=True)) == [2, 1]
    client.post(f"/wiki/pagine/{p.pk}/versione/1/ripristina/")
    p.refresh_from_db()
    assert p.testo == "Prima stesura" and p.versioni.count() == 3
    rimborsi = PaginaWiki.objects.create(azienda=s["azienda"], spazio=s["procedure"], titolo="Rimborsi", padre=p)
    p.testo = "Vedi [[Rimborsi]] e [[Trasferte]]."
    p.save()
    html = str(servizi.rendi(p))
    assert f"/wiki/pagine/{rimborsi.pk}/" in html and "da scrivere" in html
    assert servizi.citata_da(rimborsi) == [p]
    assert "Pagine qui sotto" in client.get(f"/wiki/pagine/{p.pk}/").content.decode()
    p.padre = rimborsi
    with pytest.raises(ValidationError):
        p.full_clean()
