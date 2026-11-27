"""App riservate ad alcune aziende (Modulo.aziende): con un'altra azienda corrente non si vedono (barra, ricerca, Ada)
e le pagine propongono di passare all'azienda giusta. Vale anche per i superuser."""
from html import unescape

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
    slug = next(s for s in ("crm", "todo") if s in settings.ADDONS_ATTIVI)      # app che nessun'altra usa
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


def _bearer(utente):
    from core.models import TokenApi
    _, chiaro = TokenApi.genera(utente, "prova")
    return {"HTTP_AUTHORIZATION": f"Bearer {chiaro}"}


def _api_di(slug):
    from core.viste import registry
    vista = next(v for v in registry.viste_di(slug) if v.api)
    return f"/api/v1/{slug}/{vista.slug}/"


def test_le_api_rispettano_l_azienda(scena):
    """Con il token il middleware vede l'anonimo, e X-Azienda cambia azienda dopo il middleware: il controllo va
    ripetuto quando l'azienda della chiamata è nota. Anche /me/ elenca solo le app dell'azienda della chiamata."""
    c, slug, h = scena["c"], scena["slug"], _bearer(scena["u"])
    url = _api_di(slug)
    c.logout()
    assert c.get(url, HTTP_X_AZIENDA=str(scena["zen"].pk), **h).status_code == 200
    r = c.get(url, HTTP_X_AZIENDA=str(scena["iem"].pk), **h)
    assert r.status_code == 403 and "azienda" in r.json()["detail"]
    me = c.get("/api/v1/me/", HTTP_X_AZIENDA=str(scena["iem"].pk), **h).json()
    assert slug not in [a["slug"] for a in me["app"]]


def test_api_con_la_sessione_e_l_azienda_sbagliata_rispondono_json(scena):
    c, slug = scena["c"], scena["slug"]
    _scegli(c, scena["iem"])
    r = c.get(_api_di(slug))
    assert r.status_code == 403 and r["Content-Type"].startswith("application/json")
    assert scena["zen"].nome in r.json()["detail"]
    _scegli(c, scena["zen"])                                                    # la sessione su Zen, X-Azienda su IEM
    assert c.get(_api_di(slug), HTTP_X_AZIENDA=str(scena["iem"].pk)).status_code == 403


def test_ada_non_ha_gli_strumenti_dell_app_con_un_altra_azienda(scena):
    from ai.strumenti import registro
    slug, u = "calendario", scena["u"]                    # un'app con strumenti suoi
    Modulo.objects.get(slug=slug).aziende.set([scena["zen"]])
    u._app_aziende = None
    nella = {s.app for s in registro.disponibili(u, azienda=scena["zen"])}
    u._app_aziende = None
    fuori = {s.app for s in registro.disponibili(u, azienda=scena["iem"])}
    assert slug in nella and slug not in fuori


def test_le_richieste_fuori_dal_browser_portano_l_azienda(scena):
    """Worker e Ada: app_visibili(request.user), chiamata senza azienda, deve usare l'azienda della richiesta."""
    from ai.strumenti import richiesta
    slug, u = scena["slug"], scena["u"]
    for req in (interroga.richiesta_di(u, scena["iem"]), richiesta.nuova(u, scena["iem"])):
        assert slug not in [a["slug"] for a in modules.app_visibili(req.user)]
    assert slug in [a["slug"] for a in modules.app_visibili(interroga.richiesta_di(u, scena["zen"]).user)]


def test_le_richieste_per_un_altra_azienda_non_cambiano_quella_della_pagina(scena):
    """Il consolidato su più aziende (interroga._aggrega_aziende, _kpi_aziende) chiama richiesta_di con l'utente della
    pagina, una volta per azienda: dopo, barra e menu della pagina devono restare quelli dell'azienda corrente."""
    from ai.strumenti import richiesta
    slug, u = scena["slug"], scena["u"]
    u._azienda_corrente = scena["zen"]                   # come il middleware
    interroga.richiesta_di(u, scena["iem"])
    richiesta.nuova(u, scena["iem"])
    assert u._azienda_corrente == scena["zen"]
    assert slug in [a["slug"] for a in modules.app_visibili(u)]


def test_le_aziende_disattivate_non_contano(scena):
    """Riservata solo a un'azienda poi disattivata: l'app non deve sparire per tutti."""
    slug, u, iem = scena["slug"], scena["u"], scena["iem"]
    Modulo.objects.get(slug=slug).aziende.set([iem])
    iem.attiva = False
    iem.save()
    u._app_aziende = None
    assert modules.per_azienda(slug, scena["zen"], u)


def test_scheda_aziende_senza_spunte_non_salva_per_tutte(scena):
    c, slug = scena["c"], scena["slug"]
    r = c.post(reverse("core:applicazione_aziende", args=[slug]), {"tutte": "0"}, follow=True)
    assert list(Modulo.objects.get(slug=slug).aziende.all()) == [scena["zen"]]          # invariata
    assert "Spunta almeno un'azienda" in unescape(r.content.decode())


def test_scheda_aziende_solo_per_le_applicazioni(scena):
    servizio = next((s for s, m in modules.manifests_attivi().items() if not m.application), None)
    if servizio is None:
        pytest.skip("nessun modulo di servizio attivo")
    r = scena["c"].post(reverse("core:applicazione_aziende", args=[servizio]), {"tutte": "0", "aziende": [scena["zen"].pk]})
    assert r.status_code in (302, 404)
    assert not Modulo.objects.filter(slug=servizio, aziende__isnull=False).exists()


def test_non_si_riserva_un_app_che_serve_ad_app_aperte_alle_altre(scena):
    """Contatti serve a Vendite: riservarla a Zen con Vendite aperta a tutte romperebbe Vendite in IEM. La scheda
    rifiuta e dice quali app la usano; riservate anche quelle, si può."""
    if "vendite" not in settings.ADDONS_ATTIVI:
        pytest.skip("serve vendite")
    c, zen = scena["c"], scena["zen"]
    Modulo.objects.get(slug="vendite").aziende.clear()
    r = c.post(reverse("core:applicazione_aziende", args=["contatti"]), {"tutte": "0", "aziende": [zen.pk]}, follow=True)
    testo = unescape(r.content.decode())
    assert not Modulo.objects.get(slug="contatti").aziende.exists()
    assert "Vendite" in testo and "la usano" in testo
    info = modules.scopri()
    for s in modules.manifests_attivi():                         # chi usa contatti, anche indirettamente, solo per Zen
        if s != "contatti" and "contatti" in modules.dipendenze_tutte(s, info):
            Modulo.objects.get(slug=s).aziende.set([zen])
    c.post(reverse("core:applicazione_aziende", args=["contatti"]), {"tutte": "0", "aziende": [zen.pk]})
    assert list(Modulo.objects.get(slug="contatti").aziende.all()) == [zen]
