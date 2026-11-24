"""La prima pagina (`/` e dopo il login) è la prima voce della barra in alto come la vede l'utente."""
import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from core import barra
from core.models import ProfiloUtente


def _home(client):
    r = client.get("/")
    assert r.status_code == 302
    return r["Location"]


@pytest.mark.django_db
def test_senza_scelta_della_barra_va_alla_chat(client, superuser):
    assert _home(client) == reverse("ai:chat")


@pytest.mark.django_db
def test_senza_app_in_testa_va_alla_dashboard(client, superuser, settings):
    settings.NAV_APP_IN_TESTA = []
    assert _home(client) == reverse("core:dashboard")


@pytest.mark.django_db
def test_barra_dell_azienda_che_comincia_dalla_dashboard(client, superuser):
    barra.scrivi(["dashboard", "ai", "crm"], 6)
    assert _home(client) == reverse("core:dashboard")
    client.logout()
    r = client.post(reverse("login"), {"username": "root", "password": "pass12345!"}, REMOTE_ADDR="10.0.0.1", follow=True)
    assert [url for url, _ in r.redirect_chain] == [reverse("core:home"), reverse("core:dashboard")]


@pytest.mark.django_db
def test_vale_la_barra_della_persona_e_non_quella_dell_azienda(client, superuser):
    barra.scrivi(["dashboard", "ai"], 6)
    ProfiloUtente.objects.update_or_create(utente=superuser, defaults={"barra": {"fisse": ["crm", "dashboard"], "completa": True}})
    assert _home(client) == reverse("crm:opportunita_kanban")


@pytest.mark.django_db
def test_prima_voce_non_vista_si_passa_alla_successiva(client, db):
    barra.scrivi(["crm", "todo", "dashboard"], 6)
    u = User.objects.create_user("lia", "lia@example.com", "pass12345!")
    u.user_permissions.add(Permission.objects.get(codename="view_attivita", content_type__app_label="todo"))
    client.force_login(u)
    assert _home(client) == reverse("todo:attivita_lista")          # il CRM non lo vede


@pytest.mark.django_db
def test_barra_vuota_va_alla_dashboard(client, superuser):
    barra.scrivi([], 6, nascoste=["dashboard", "ai"])
    assert _home(client) == reverse("core:dashboard")             # barra vuota: comunque una pagina


# ---------- la prima pagina scelta da chi amministra, per ruolo o per persona ----------

def _operatore(client, ruolo=None, **profilo):
    from core.models import Azienda
    u = User.objects.create_user("olga", "olga@example.com", "x")
    u.user_permissions.add(Permission.objects.get(codename="add_conversazione", content_type__app_label="ai"),
                           Permission.objects.get(codename="view_conversazione", content_type__app_label="ai"))
    u.profilo.aziende.set([Azienda.objects.first()])
    ProfiloUtente.objects.filter(utente=u).update(ruolo=ruolo, **profilo)
    client.force_login(User.objects.get(pk=u.pk))
    return User.objects.get(pk=u.pk)


@pytest.mark.django_db
def test_la_prima_pagina_del_ruolo_dopo_l_accesso_e_dall_app(client):
    from core.models import Ruolo
    operatori = Ruolo.objects.create(nome="Operatori", prima_pagina="core:dashboard")
    _operatore(client, operatori)
    assert _home(client) == reverse("core:dashboard")                      # senza la scelta sarebbe la chat
    r = client.get("/tasca/?da=app")
    assert r.status_code == 302 and r["Location"] == reverse("core:dashboard")
    assert client.get("/tasca/").status_code == 200                        # aperta a mano resta «In tasca»
    Ruolo.objects.filter(pk=operatori.pk).update(prima_pagina="")           # senza scelta: tutto come prima
    assert _home(client) == reverse("ai:chat") and client.get("/tasca/?da=app").status_code == 200


@pytest.mark.django_db
def test_la_scelta_per_la_persona_vince_su_quella_del_ruolo(client):
    from core.models import Ruolo
    _operatore(client, Ruolo.objects.create(nome="Operatori", prima_pagina="core:dashboard"), prima_pagina="core:tasca")
    assert _home(client) == reverse("core:tasca")
    assert client.get("/tasca/?da=app").status_code == 200                 # «In tasca» come prima pagina: è questa pagina


@pytest.mark.django_db
def test_una_prima_pagina_che_la_persona_non_puo_aprire_si_ignora(client):
    from core.models import Ruolo
    from core.registry import modules
    voce = modules.manifests_attivi()["crm"].menu[0]
    utente = _operatore(client, Ruolo.objects.create(nome="Operatori", prima_pagina=voce["url_name"]))
    assert _home(client) == reverse("ai:chat") and client.get("/tasca/?da=app").status_code == 200
    app, codice = voce["permission"].split(".")
    utente.user_permissions.add(Permission.objects.get(codename=codice, content_type__app_label=app))
    client.force_login(User.objects.get(pk=utente.pk))
    assert _home(client) == reverse(voce["url_name"])
    ProfiloUtente.objects.filter(utente=utente).update(prima_pagina="modulo:sparito")     # un'app disinstallata
    assert _home(client) == reverse("ai:chat")


@pytest.mark.django_db
def test_la_scelta_personale_dell_app_installata_resta(client):
    """Chi nel suo profilo ha scelto «Parla con Ada» o «Chat» per l'app installata la tiene: la prima pagina del ruolo
    vale per chi non ha scelto."""
    from core.models import Ruolo
    _operatore(client, Ruolo.objects.create(nome="Operatori", prima_pagina="core:dashboard"), apertura_app="chat")
    r = client.get("/tasca/?da=app")
    assert r.status_code == 302 and r["Location"] == reverse("ai:chat")
    assert _home(client) == reverse("core:dashboard")                      # dal computer vale la prima pagina del ruolo
    # la sua scelta non si può più aprire (permesso tolto, Ada spenta): non «In tasca», ma la prima pagina del ruolo
    olga = User.objects.get(username="olga")
    olga.user_permissions.clear()
    client.force_login(User.objects.get(pk=olga.pk))
    r = client.get("/tasca/?da=app")
    assert r.status_code == 302 and r["Location"] == reverse("core:dashboard")
    assert client.get("/tasca/?apri=chat").status_code == 200              # la scorciatoia dell'icona resta su «In tasca»


@pytest.mark.django_db
def test_chi_amministra_la_sceglie_dal_ruolo_e_dalla_scheda_della_persona(client, superuser):
    from core.models import Ruolo
    from core.utenti import RuoloForm
    form = RuoloForm({"nome": "Operatori", "livello_base": "lavoro", "ordine": 10, "prima_pagina": "core:dashboard"})
    assert form.is_valid(), form.errors
    assert form.save().prima_pagina == "core:dashboard"
    assert "Dashboard" in dict(form.fields["prima_pagina"].choices).values()
    assert any("·" in etichetta for etichetta in dict(form.fields["prima_pagina"].choices).values())      # «App · Voce»
    assert not RuoloForm({"nome": "Altri", "livello_base": "lavoro", "ordine": 10, "prima_pagina": "https://altro.sito/"}).is_valid()
    pagina = client.get(reverse("core:ruolo", args=[Ruolo.objects.get(nome="Operatori").pk])).content.decode()
    assert 'name="prima_pagina"' in pagina and "Prima pagina" in pagina
    olga = User.objects.create_user("olga", "olga@example.com", "x")
    scheda = client.get(reverse("core:utente", args=[olga.pk])).content.decode()
    assert 'name="prima_pagina"' in scheda and "Quella del suo ruolo" in scheda
    r = client.post(reverse("core:utente", args=[olga.pk]), {"first_name": "Olga", "last_name": "Neri", "email": "olga@example.com",
                                                             "username": "olga", "is_active": "on", "prima_pagina": "core:tasca"})
    assert r.status_code == 302 and ProfiloUtente.objects.get(utente=olga).prima_pagina == "core:tasca"
