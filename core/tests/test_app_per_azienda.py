"""App riservate ad alcune aziende (Modulo.aziende): con un'altra azienda corrente non si vedono (barra, ricerca, Ada)
e le pagine propongono di passare all'azienda giusta. Vale anche per i superuser."""
import pytest
from django.conf import settings
from django.urls import reverse

from core import azienda as az
from core.models import Azienda, Modulo, ProfiloUtente
from core.registry import modules
from core.viste import interroga

pytestmark = pytest.mark.django_db


@pytest.fixture
def scena(superuser, client):
    slug = next(s for s in ("vendite", "crm", "todo") if s in settings.ADDONS_ATTIVI)
    modules.sincronizza()
    zen, iem = Azienda.objects.get(pk=1), Azienda.objects.create(nome="IEM Srl")
    profilo, _ = ProfiloUtente.objects.get_or_create(utente=superuser)
    profilo.aziende.add(zen, iem)
    Modulo.objects.get(slug=slug).aziende.set([zen])
    return {"slug": slug, "zen": zen, "iem": iem, "u": superuser, "c": client}


def _scegli(client, azienda):
    sessione = client.session
    sessione[az.CHIAVE_SESSIONE] = azienda.pk
    sessione.save()


def _primo_url(slug, user, azienda):
    return next(a["url"] for a in modules.app_visibili(user, azienda=azienda) if a["slug"] == slug)


def test_l_app_si_vede_solo_con_le_sue_aziende(scena):
    slug, u = scena["slug"], scena["u"]
    assert slug in [a["slug"] for a in modules.app_visibili(u, azienda=scena["zen"])]
    u._app_aziende = None
    assert slug not in [a["slug"] for a in modules.app_visibili(u, azienda=scena["iem"])]
    assert slug in [a["slug"] for a in modules.app_visibili(u, azienda=None)]      # senza azienda: nessun limite
    assert modules.per_azienda("altra_app", scena["iem"])                         # le app non riservate: tutte


def test_l_azienda_corrente_arriva_dal_middleware(scena):
    """app_visibili(user), chiamata senza azienda in tanti punti, usa l'azienda corrente che il middleware ha messo
    sull'utente."""
    c, slug = scena["c"], scena["slug"]
    _scegli(c, scena["iem"])
    utente = c.get(reverse("core:profilo")).wsgi_request.user
    assert utente._azienda_corrente == scena["iem"]
    assert slug not in [a["slug"] for a in modules.app_visibili(utente)]


def test_la_pagina_con_l_azienda_sbagliata_propone_di_cambiarla(scena):
    c, slug = scena["c"], scena["slug"]
    url = _primo_url(slug, scena["u"], scena["zen"])
    _scegli(c, scena["iem"])
    r = c.get(url)
    html = r.content.decode()
    assert r.status_code == 403 and "è di un'altra azienda" in html and f"Passa a {scena['zen']}" in html
    assert f'name="next" value="{url}"' in html
    r = c.post(reverse("core:cambia_azienda"), {"azienda": scena["zen"].pk, "next": url})
    assert r.status_code == 302 and r["Location"] == url
    assert c.get(url).status_code == 200


def test_ada_non_vede_le_viste_dell_app_con_un_altra_azienda(scena):
    from ai.strumenti import richiesta
    slug = scena["slug"]
    nella = {interroga.id_vista(v).split(".")[0] for v in interroga.viste_accessibili(richiesta.nuova(scena["u"], scena["zen"]))}
    scena["u"]._app_aziende = None
    fuori = {interroga.id_vista(v).split(".")[0] for v in interroga.viste_accessibili(richiesta.nuova(scena["u"], scena["iem"]))}
    assert slug in nella and slug not in fuori


def test_scheda_del_modulo_sceglie_le_aziende(scena):
    c, slug = scena["c"], scena["slug"]
    html = c.get(reverse("core:applicazione", args=[slug])).content.decode()
    assert "Solo per queste aziende" in html and "IEM Srl" in html
    c.post(reverse("core:applicazione_aziende", args=[slug]), {"tutte": "0", "aziende": [scena["iem"].pk]})
    assert list(Modulo.objects.get(slug=slug).aziende.all()) == [scena["iem"]]
    c.post(reverse("core:applicazione_aziende", args=[slug]), {"tutte": "1", "aziende": [scena["iem"].pk]})
    assert not Modulo.objects.get(slug=slug).aziende.exists()
