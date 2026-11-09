"""Personalizzazioni: campo personalizzato che collega un record (solo della stessa azienda), voci di menu interne
rinominate, spostate e nascoste per tutti o per un ruolo."""
import pytest
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType

from contatti.models import Contatto
from core import proprieta
from core.models import Azienda, CampoPersonalizzato, Ruolo, VoceMenu
from core.registry import modules
from progetti.models import Progetto


@pytest.fixture
def s(db):
    azienda = Azienda.objects.get(pk=1)
    altra = Azienda.objects.create(nome="Altra")
    return {"azienda": azienda, "altra": altra, "root": User.objects.create_superuser("root", "r@x.it", "x")}


def test_campo_collegamento(client, s):
    CampoPersonalizzato.objects.create(modello=ContentType.objects.get_for_model(Contatto), nome="progetto_principale", label="Progetto principale",
                                       tipo="record", collega_a=ContentType.objects.get_for_model(Progetto))
    mio = Progetto.objects.create(azienda=s["azienda"], nome="Sito")
    Progetto.objects.create(azienda=s["altra"], nome="Segreto")
    client.force_login(s["root"])
    html = client.get("/contatti/contatti/nuovo/").content.decode()
    assert "Progetto principale" in html and "Sito" in html and "Segreto" not in html
    r = client.post("/contatti/contatti/nuovo/", {"nome": "Rossi", "tipo": "azienda", "nazione": "IT", "prop_progetto_principale": mio.pk, "cliente": "on"})
    c = Contatto.objects.get(nome="Rossi")
    assert r.status_code == 302 and c.proprieta["progetto_principale"] == mio.pk
    d = proprieta.definizioni(Contatto, s["azienda"])[0]
    assert proprieta.testo(d, c) == "Sito"


def test_voci_di_menu(client, s):
    client.force_login(s["root"])
    client.post("/applicazioni/progetti/menu/", {"nome_0": "I nostri lavori", "ordine_0": "99", "nascosta_1": "1"})
    menu = next(a for a in modules.app_visibili(s["root"]) if a["slug"] == "progetti")["menu"]
    assert menu[-1]["label"] == "I nostri lavori" and VoceMenu.objects.filter(nascosta=True).count() == 1
    ruolo = Ruolo.objects.first()
    client.post("/applicazioni/progetti/menu/", {"ruolo": ruolo.pk, "nome_0": "Commesse"})
    u = User.objects.create_superuser("capo", "c@x.it", "x")
    u.profilo.ruolo = ruolo
    u.profilo.save()
    menu = next(a for a in modules.app_visibili(User.objects.get(pk=u.pk)) if a["slug"] == "progetti")["menu"]
    assert any(v["label"] == "Commesse" for v in menu)
    assert "Voci del menu" in client.get("/applicazioni/progetti/").content.decode()
    client.post("/applicazioni/progetti/menu/", {})
    assert not VoceMenu.objects.filter(ruolo__isnull=True).exists()                     # tutto come il modulo: niente righe
