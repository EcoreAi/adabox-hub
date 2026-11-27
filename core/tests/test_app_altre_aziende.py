"""App delle altre aziende nella barra in alto: chi lavora in più aziende vede anche le app che avrebbe in barra nelle
altre (es. riservate a quelle con Modulo.aziende), con il nome dell'azienda di arrivo. Al clic lo script del tema
(theme/cambia_azienda.js) scrive azienda e indirizzo nel form nascosto e lo invia (POST a core:cambia_azienda); senza
script, o aprendo il link in un'altra scheda, risponde la pagina «Passa a …» del kernel. Chi ha una sola azienda vede
l'header di sempre.

Lo script è provato fuori dal repository con jsdom (la CI non ha un DOM): qui si controlla che ci sia, che sia incluso e
che faccia quelle cose."""
import re

import pytest
from django.contrib.auth.models import Permission, User
from django.contrib.messages import get_messages
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.template import engines
from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import reverse

from core import altre_aziende, barra
from core.middleware import AziendaCorrenteMiddleware
from core.models import Azienda, Dipartimento, Modulo, Parametro, ProfiloUtente
from core.registry import modules

pytestmark = pytest.mark.django_db

SLUG = "vendite"
MARCATORI = ("data-cambia-azienda", "ui-nav-altra-azienda", "theme/cambia_azienda.js")


@pytest.fixture
def scena(superuser, client):
    """Il superuser lavora in due aziende; la corrente è la predefinita (zen), Vendite è solo dell'altra (iem)."""
    modules.sincronizza()
    zen, iem = Azienda.objects.get(pk=1), Azienda.objects.create(nome="IEM Srl")
    profilo, _ = ProfiloUtente.objects.get_or_create(utente=superuser)      # nato con la sola zen, la predefinita
    profilo.aziende.add(zen, iem)
    Modulo.objects.get(slug=SLUG).aziende.set([iem])
    return {"zen": zen, "iem": iem, "u": superuser, "c": client}


def _richiesta(user):
    request = RequestFactory().get("/")
    SessionMiddleware(lambda r: HttpResponse()).process_request(request)
    request.user = User.objects.get(pk=user.pk)          # niente memorie sull'oggetto (dipartimenti, aziende delle app)
    AziendaCorrenteMiddleware(lambda r: HttpResponse())(request)
    return request


def _primo_url(user, azienda):
    return next(a["url"] for a in modules.app_visibili(User.objects.get(pk=user.pk), azienda=azienda) if a["slug"] == SLUG)


def _header(client):
    html = client.get(reverse("core:profilo")).content.decode()
    inizio = html.index('<header class="ui-header">')
    return html[inizio:html.index('<main class="ui-shell">', inizio)]     # nell'header ci sono altri <header>


def _sorgente(nome):
    return get_template(nome).template.source


def _link(html, slug_url):
    return re.search(r'<a href="' + re.escape(slug_url) + r'"[^>]*data-cambia-azienda="(\d+)"[^>]*>(.*?)</a>', html, re.S)


def _form(html):
    return re.search(r"<form[^>]*data-cambia-azienda-form[^>]*>(.*?)</form>", html, re.S)


def test_le_voci_delle_altre_aziende(scena):
    voci = altre_aziende.voci(_richiesta(scena["u"]))
    assert voci == [{"slug": SLUG, "label": "Vendite", "url": _primo_url(scena["u"], scena["iem"]),
                     "azienda_pk": scena["iem"].pk, "azienda_nome": "IEM Srl", "solo_computer": False}]


def test_nella_barra_il_link_all_app_dell_altra_azienda(scena):
    c, iem = scena["c"], scena["iem"]
    url = _primo_url(scena["u"], iem)
    header = _header(c)
    link = _link(header, url)
    assert link and link.group(1) == str(iem.pk)
    assert "Vendite" in link.group(2) and "IEM Srl" in link.group(2)
    assert 'class="ui-nav-altra-azienda' in link.group(0)
    nav = header[header.index('<nav class="ui-nav"'):header.index("</nav>")]
    assert link.group(0) in nav                                         # un link del menu: la ricerca del telefono lo trova
    if "ui-nav-altre" in nav:
        assert nav.index(link.group(0)) < nav.index('class="ui-dropdown ui-nav-altre"')       # prima di «Altre»

    form = _form(header)
    assert form and f'action="{reverse("core:cambia_azienda")}"' in form.group(0) and 'method="post"' in form.group(0)
    assert " hidden" in form.group(0).split(">")[0]
    assert 'name="csrfmiddlewaretoken"' in form.group(1)
    assert 'name="azienda"' in form.group(1) and 'name="next"' in form.group(1)
    assert header.count("data-cambia-azienda-form") == 1
    assert "theme/cambia_azienda.js" in header


def test_senza_script_il_link_propone_di_passare_all_altra_azienda_e_il_post_apre_l_app(scena):
    c, iem = scena["c"], scena["iem"]
    url = _primo_url(scena["u"], iem)
    r = c.get(url)                                                      # clic centrale, nuova scheda, niente script
    assert r.status_code == 403 and f"Passa a {iem}" in r.content.decode()
    r = c.post(reverse("core:cambia_azienda"), {"azienda": iem.pk, "next": url})     # quello che invia lo script
    assert r.status_code == 302 and r["Location"] == url
    assert "Azienda corrente: IEM Srl." in [str(m) for m in get_messages(r.wsgi_request)]
    r = c.get(url)
    assert r.status_code == 200 and r.wsgi_request.azienda == iem
    assert not _link(_header(c), url)                                  # ora è un'app dell'azienda corrente


def test_con_l_app_in_entrambe_le_aziende_nessuna_voce_in_piu(scena):
    Modulo.objects.get(slug=SLUG).aziende.set([scena["zen"], scena["iem"]])
    assert altre_aziende.voci(_richiesta(scena["u"])) == []
    Modulo.objects.get(slug=SLUG).aziende.clear()                       # per tutte
    assert altre_aziende.voci(_richiesta(scena["u"])) == []
    header = _header(scena["c"])
    assert "data-cambia-azienda=" not in header and "ui-nav-altra-azienda" not in header
    assert _form(header)                                                # il form c'è comunque: lo usa anche la chat


def test_un_app_in_piu_altre_aziende_una_voce_sola_per_la_prima_per_nome(scena):
    zeta = Azienda.objects.create(nome="Zeta Srl")
    beta = Azienda.objects.create(nome="Beta Srl")
    scena["u"].profilo.aziende.add(zeta, beta)
    Modulo.objects.get(slug=SLUG).aziende.set([scena["iem"], zeta, beta])
    voci = altre_aziende.voci(_richiesta(scena["u"]))
    assert [(v["slug"], v["azienda_nome"]) for v in voci] == [(SLUG, "Beta Srl")]


def test_senza_l_app_nell_altra_azienda_nessuna_voce(scena):
    """L'altra azienda c'è, ma l'app no: fuori dal dipartimento o senza permessi."""
    u = User.objects.create_user("titolare", password="pass12345!")        # nato con tutte e due le aziende
    ProfiloUtente.objects.filter(utente=u).update(azienda_predefinita=scena["zen"], ruolo=None)
    u.groups.clear()
    assert altre_aziende.voci(_richiesta(u)) == []                      # senza permessi su Vendite
    u.user_permissions.add(Permission.objects.get(content_type__app_label="vendite", codename="view_ordinevendita"))
    assert [v["slug"] for v in altre_aziende.voci(_richiesta(u))] == [SLUG]
    u.profilo.dipartimenti.add(Dipartimento.objects.create(nome="Marketing", app=["crm"]))
    assert altre_aziende.voci(_richiesta(u)) == []                      # fuori dal suo dipartimento


def test_le_app_che_non_hanno_una_voce_in_barra_non_compaiono(scena, settings):
    """Come la barra: niente app nascoste dalla scelta della barra, niente app che sono schede della Dashboard."""
    barra.scrivi([], 4, nascoste=[SLUG])
    assert altre_aziende.voci(_richiesta(scena["u"])) == []
    Parametro.objects.filter(chiave=barra.CHIAVE).delete()
    Modulo.objects.get(slug=SLUG).aziende.clear()
    Modulo.objects.get(slug="grafici").aziende.set([scena["iem"]])
    assert "grafici" in [a["slug"] for a in modules.app_visibili(User.objects.get(pk=scena["u"].pk), azienda=scena["iem"])]
    assert altre_aziende.voci(_richiesta(scena["u"])) == []
    settings.NAV_SOLO_COMPUTER = [SLUG]                               # sul telefono come le altre: solo cercandole
    Modulo.objects.get(slug=SLUG).aziende.set([scena["iem"]])
    assert [v["solo_computer"] for v in altre_aziende.voci(_richiesta(scena["u"]))] == [True]
    assert "ui-nav-altra-azienda is-solo-computer" in _header(scena["c"])


def test_con_una_sola_azienda_l_header_non_cambia(scena, monkeypatch):
    scena["u"].profilo.aziende.remove(scena["iem"])
    header = _header(scena["c"])
    assert not [m for m in MARCATORI if m in header]
    assert reverse("core:cambia_azienda") not in header and "data-cambia-azienda-form" not in header

    def niente(*a, **k):
        raise AssertionError("con una sola azienda non si calcola nulla")
    monkeypatch.setattr(modules, "app_visibili", niente)
    assert altre_aziende.voci(_richiesta(scena["u"])) == []


def _header_oggi_e_prima(client):
    """L'header di oggi e quello senza i due pezzi nuovi, resi per la stessa richiesta (token CSRF a parte)."""
    request = client.get(reverse("core:profilo")).wsgi_request
    sorgente = _sorgente("theme/partials/_header.html")
    for pezzo in ("_altre_aziende", "_cambia_azienda"):
        sorgente = sorgente.replace('{% include "theme/partials/' + pezzo + '.html" %}', "")
    token = re.compile(r'name="csrfmiddlewaretoken" value="[^"]*"')
    oggi = get_template("theme/partials/_header.html").render(request=request)
    prima = engines["django"].from_string(sorgente).render(request=request)
    return token.sub("", oggi), token.sub("", prima)


def test_con_una_sola_azienda_l_header_e_quello_di_prima_byte_per_byte(scena):
    oggi, prima = _header_oggi_e_prima(scena["c"])
    assert oggi != prima                                                # con due aziende i pezzi scrivono qualcosa
    scena["u"].profilo.aziende.remove(scena["iem"])
    oggi, prima = _header_oggi_e_prima(scena["c"])
    assert oggi == prima                                                # con una: nemmeno uno spazio in più


def test_l_azienda_disattivata_non_conta(scena):
    Azienda.objects.filter(pk=scena["iem"].pk).update(attiva=False)
    assert altre_aziende.voci(_richiesta(scena["u"])) == []
    header = _header(scena["c"])
    assert not [m for m in MARCATORI if m in header]


def test_le_voci_si_calcolano_una_volta_per_richiesta(scena, monkeypatch):
    chiamate = []
    originale = modules.app_visibili

    def contata(*a, **k):
        chiamate.append(1)
        return originale(*a, **k)
    monkeypatch.setattr(modules, "app_visibili", contata)
    request = _richiesta(scena["u"])
    prime = altre_aziende.voci(request)
    n = len(chiamate)
    assert prime and altre_aziende.voci(request) == prime and len(chiamate) == n


def test_lo_script_del_cambio_c_e_ed_e_incluso_dal_suo_pezzo_di_template():
    js = open(finders.find("theme/cambia_azienda.js"), encoding="utf-8").read()
    assert "document.addEventListener('click'" in js                   # delega: vale anche per i link arrivati dopo
    assert "closest('a[data-cambia-azienda]')" in js and "[data-cambia-azienda-form]" in js
    assert "e.button !== 0" in js and all(t in js for t in ("e.ctrlKey", "e.metaKey", "e.shiftKey", "e.altKey"))
    assert "e.defaultPrevented" in js and "e.preventDefault()" in js
    assert "getAttribute('href')" in js and ".submit()" in js
    pezzo = _sorgente("theme/partials/_cambia_azienda.html")
    assert "{% statico 'theme/cambia_azienda.js' %}" in pezzo and "{% csrf_token %}" in pezzo


def test_l_header_del_kernel_include_i_due_pezzi():
    """Un tema con un suo header include gli stessi due pezzi (docs/guida-moduli.md)."""
    header = _sorgente("theme/partials/_header.html")
    voci, altre = header.index("theme.nav_principale"), header.index("{% if theme.nav_altre %}")
    pezzo = header.index('{% include "theme/partials/_altre_aziende.html" %}')
    assert voci < pezzo < altre                                         # in fondo alle voci, prima di «Altre»
    assert header.count('{% include "theme/partials/_cambia_azienda.html" %}') == 1


def test_invio_nella_ricerca_del_menu_apre_la_voce_con_un_clic():
    """Sul telefono Invio apre la prima app trovata: con un clic sul link (non andando al suo indirizzo), così una voce
    di un'altra azienda passa dallo script del cambio invece di finire sulla pagina «Passa a …»."""
    js = open(finders.find("theme/ui.js"), encoding="utf-8").read()
    invio = re.search(r"if \(e\.key !== 'Enter'\) return;(.*?)\}\);", js, re.S).group(1)
    assert "prima.click()" in invio and "location.href" not in invio
