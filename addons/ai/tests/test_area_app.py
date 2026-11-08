"""Aree di lavoro e app (fase B): un'area si collega a una o più app; in ognuna compare «Aree di lavoro» (solo per i
membri) con quello che ci nasce, e Ada sa con quali app lavora l'area."""
import pytest
from django.apps import apps
from django.contrib.auth.models import Permission

from ai import aree
from ai.contesto_utente import nota_progetto
from ai.models import Conversazione, ProgettoChat
from ai.tests.test_chat_gruppo2 import _utente, s  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not apps.is_installed("crm"), reason="serve crm")


@pytest.fixture
def m(s):
    s["u"].user_permissions.add(*Permission.objects.filter(content_type__app_label="crm"))
    area = ProgettoChat.objects.create(utente=s["u"], azienda=s["az"], nome="Marketing", app_collegate=["crm", "contatti"])
    Conversazione.objects.create(utente=s["u"], titolo="Post di novembre", progetto=area)
    return {"area": area}


def test_voce_e_pagina_nell_app(client, s, m):
    lista = client.get("/crm/opportunita/").content.decode()
    assert "/crm/aree-di-lavoro/" in lista
    pagina = client.get("/crm/aree-di-lavoro/").content.decode()
    assert "Marketing" in pagina and "Post di novembre" in pagina and "Le aree collegate a CRM" in pagina


def test_solo_per_i_membri(client, s, m):
    estraneo = _utente("dario", s["az"])
    estraneo.user_permissions.add(*Permission.objects.filter(content_type__app_label="crm"))
    client.force_login(estraneo)
    assert "/crm/aree-di-lavoro/" not in client.get("/crm/opportunita/").content.decode()
    assert "Marketing" not in client.get("/crm/aree-di-lavoro/").content.decode()
    aree.imposta_membri(m["area"], [estraneo])
    pagina = client.get("/crm/aree-di-lavoro/").content.decode()
    assert "Marketing" in pagina and "Post di novembre" not in pagina                    # chat privata di chi l'ha scritta


def test_le_app_non_collegate_non_la_mostrano(client, s, m):
    if not apps.is_installed("todo"):
        pytest.skip("todo non installato")
    s["u"].user_permissions.add(*Permission.objects.filter(content_type__app_label="todo"))
    assert "/todo/aree-di-lavoro/" not in client.get("/todo/attivita/").content.decode()


def test_ada_sa_con_quali_app_lavora(s, m):
    c = Conversazione.objects.get(titolo="Post di novembre")
    nota = nota_progetto(c)
    assert "L'area lavora con queste app" in nota and "(crm)" in nota and "(contatti)" in nota


def test_si_scelgono_nel_form_dell_area(client, s, m):
    form = client.get(f"/ai/progetti/{m['area'].pk}/modifica/").content.decode()
    assert 'name="app_collegate"' in form and 'value="crm"' in form
