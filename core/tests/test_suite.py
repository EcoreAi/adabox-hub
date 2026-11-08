"""Suite comprate dal portale, sull'istanza: il dipartimento che le segue, le app comuni, i posti, il catalogo."""
import datetime
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from core import dipartimenti, licenza
from core.models import Dipartimento, LicenzaIstanza, Modulo, RichiestaModulo
from core.registry import pacchetti, sincronia
from core.utenti import UtenteForm


@pytest.fixture
def chiave(settings):
    privata = Ed25519PrivateKey.generate()
    settings.MODULI_CHIAVI_FIDATE = [pacchetti.pubblica_b64(privata)]
    return privata


def _file(chiave, suite=(), comuni=("todo",), emessa="2026-11-08T10:00:00"):
    scadenza = timezone.localdate() + datetime.timedelta(days=100)
    dati = {"cliente": "Rossi Srl", "istanza": "abc", "piano": "Base", "moduli": ["todo", "crm", "contatti", "helpdesk", "progetti"], "utenti": 0,
            "scadenza": scadenza.isoformat(), "grazia_giorni": 30, "emessa": emessa}
    if suite:
        dati.update(suite=list(suite), comuni=list(comuni))
    return json.dumps(licenza.firma(dati, chiave))


MARKETING = {"slug": "marketing", "nome": "Marketing", "moduli": ["crm"], "utenti": 0}


@pytest.mark.django_db
def test_la_suite_fa_nascere_il_dipartimento_e_lui_la_segue(chiave):
    Modulo.objects.update_or_create(slug="todo", defaults={"nome": "To-do", "comune": False})
    stato = licenza.salva(_file(chiave, [MARKETING]))
    assert stato.suite[0]["moduli"] == {"crm"} and stato.comuni == {"todo"}
    d = Dipartimento.objects.get(suite="marketing")
    assert d.nome == "Marketing" and d.app == ["crm"] and d.app_suite == ["crm"]
    assert Modulo.objects.get(slug="todo").comune                             # piano base: comune alla prima licenza a suite
    d.app = ["crm", "progetti"]                                               # l'Admin aggiunge un'app sua
    d.save()
    licenza.salva(_file(chiave, [{**MARKETING, "moduli": ["helpdesk"]}], emessa="2026-11-08T11:00:00"))
    d.refresh_from_db()
    assert d.app == ["helpdesk", "progetti"] and d.app_suite == ["helpdesk"]  # entra helpdesk, esce crm, progetti resta
    Modulo.objects.filter(slug="todo").update(comune=False)                  # poi le comuni le decide l'Admin
    licenza.salva(_file(chiave, [MARKETING], emessa="2026-11-08T12:00:00"))
    assert not Modulo.objects.get(slug="todo").comune and Dipartimento.objects.count() == 1


@pytest.mark.django_db
def test_si_aggancia_al_dipartimento_con_lo_stesso_nome(chiave):
    vecchio = Dipartimento.objects.create(nome="Marketing", app=["progetti"])
    licenza.salva(_file(chiave, [MARKETING]))
    vecchio.refresh_from_db()
    assert Dipartimento.objects.count() == 1 and vecchio.suite == "marketing" and vecchio.app == ["crm", "progetti"]


@pytest.mark.django_db
def test_posti_della_suite(chiave, settings):
    settings.LICENZA_OBBLIGATORIA = True
    licenza.salva(_file(chiave, [{**MARKETING, "utenti": 1}]))
    marketing = Dipartimento.objects.get(suite="marketing")
    altro = Dipartimento.objects.create(nome="Progetti", app=["progetti"])
    uno = User.objects.create_user("uno")
    uno.profilo.dipartimenti.add(marketing)
    assert dipartimenti.posti_suite()[0]["occupati"] == 1 and licenza.avviso() == ""
    form = UtenteForm({"username": "due", "email": "d@example.com", "is_active": True, "dipartimenti": []})
    assert not form.is_valid() and "La suite Marketing copre 1 persona" in str(form.errors["dipartimenti"])   # senza dipartimenti vede tutto
    assert UtenteForm({"username": "due", "email": "d@example.com", "is_active": True, "dipartimenti": [altro.pk]}).is_valid()
    assert UtenteForm({"username": "due", "email": "d@example.com", "is_active": False, "dipartimenti": []}).is_valid()
    assert UtenteForm({"username": "uno", "email": "u@example.com", "is_active": True, "dipartimenti": [marketing.pk]}, instance=uno).is_valid()
    User.objects.create_user("tre")                                           # entrato da un'altra strada: solo l'avviso
    assert "La suite Marketing ha 2 persone su 1 posti" in licenza.avviso()


@pytest.mark.django_db
def test_dipartimento_oltre_i_posti(chiave, client):
    licenza.salva(_file(chiave, [{**MARKETING, "utenti": 1}]))
    capo = User.objects.create_superuser("capo", "c@example.com", "x")
    client.force_login(capo)
    progetti = Dipartimento.objects.create(nome="Progetti", app=["progetti"])
    a, b = User.objects.create_user("a"), User.objects.create_user("b")
    for u in (a, b):
        u.profilo.dipartimenti.add(progetti)
    marketing = Dipartimento.objects.get(suite="marketing")
    r = client.post(f"/utenti/dipartimenti/{marketing.pk}/", {"nome": "Marketing", "ordine": 10, "app": ["crm"], "membri": [a.pk, b.pk]})
    assert r.status_code == 200 and "copre 1 persona" in r.content.decode() and not marketing.profili.exists()
    assert client.post(f"/utenti/dipartimenti/{marketing.pk}/", {"nome": "Marketing", "ordine": 10, "app": ["crm"], "membri": [a.pk]}).status_code == 302
    html = client.get(f"/utenti/dipartimenti/{marketing.pk}/").content.decode()
    assert "1 su 1 posti" in html and "Nato dalla suite" in html


@pytest.mark.django_db
def test_catalogo_e_richiesta_della_suite(chiave, client, settings):
    settings.LICENZA_OBBLIGATORIA = True
    capo = User.objects.create_superuser("capo", "c@example.com", "x")
    client.force_login(capo)
    catalogo = {"istanza": "abc", "moduli": [], "disponibili": [], "suite": [
        {"slug": "marketing", "nome": "Marketing", "descrizione": "Lead e campagne", "utenti": 5, "comprata": True, "moduli": [{"slug": "crm", "nome": "CRM"}]},
        {"slug": "vendite", "nome": "Vendite", "descrizione": "Dal preventivo alla fattura", "utenti": 0, "comprata": False,
         "moduli": [{"slug": "vendite", "nome": "Vendite"}, {"slug": "prodotti", "nome": "Prodotti"}]}]}
    licenza.salva(_file(chiave, [MARKETING]), catalogo=catalogo)
    r = client.get(reverse("core:applicazioni"))
    html = r.content.decode()
    assert "Suite per dipartimento" in html and "Dal preventivo alla fattura" in html and "Richiedi la suite" in html
    assert [(s["slug"], s["stato"]) for s in r.context["suite"]] == [("marketing", "comprata"), ("vendite", "disponibile")]
    assert client.post(reverse("core:applicazioni_richiedi"), {"slug": "marketing", "tipo": "suite"}).status_code == 404   # già comprata
    assert client.post(reverse("core:applicazioni_richiedi"), {"slug": "vendite", "tipo": "suite", "nota": "3 persone"}).status_code == 302
    richiesta = RichiestaModulo.objects.get()
    assert richiesta.tipo == "suite" and richiesta.nome == "Vendite" and richiesta.nota == "3 persone"
    assert client.post(reverse("core:applicazioni_richiedi"), {"slug": "vendite", "tipo": "suite"}).status_code == 404    # una volta sola
    assert sincronia._rapporto()["richieste"][0]["tipo"] == "suite"
    stato = licenza.salva(_file(chiave, [MARKETING, {"slug": "vendite", "nome": "Vendite", "moduli": ["vendite"], "utenti": 0}], emessa="2026-11-08T13:00:00"))
    RichiestaModulo.objects.create(slug="crm", nome="CRM")                   # una richiesta d'app con lo stesso slug di una suite non si confonde
    RichiestaModulo.objects.create(slug="vendite", nome="Vendite app")
    sincronia._aggiorna_richieste(stato, {})
    assert RichiestaModulo.objects.get(tipo="suite").stato == "evasa"
    assert RichiestaModulo.objects.get(nome="Vendite app").stato == "inviata" and RichiestaModulo.objects.get(slug="crm").stato == "evasa"
    assert Dipartimento.objects.filter(suite="vendite").exists()
    assert LicenzaIstanza.objects.get().catalogo == catalogo
