"""Aree di lavoro e record (fase A): dal record si crea un'area collegata con i colleghi del record, e nel record si
vede quello che nasce nell'area (chat visibili, documenti, grafici e tabelle), mai le chat private degli altri."""
import pytest
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ai import aree, documenti_chat
from ai.models import Artifact, CollegamentoProgetto, Conversazione, ProgettoChat
from ai.tests.test_chat_gruppo2 import _utente, s  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(not apps.is_installed("progetti"), reason="serve progetti")


@pytest.fixture
def p(s):
    from django.contrib.auth.models import Permission

    from progetti.models import Progetto
    bruno, carla = _utente("bruno", s["az"]), _utente("carla", s["az"])
    s["u"].user_permissions.add(*Permission.objects.filter(content_type__app_label="progetti"))
    progetto = Progetto.objects.create(azienda=s["az"], nome="Sito Rossi", responsabile=bruno)
    progetto.membri.set([carla])
    return {"progetto": progetto, "bruno": bruno, "carla": carla, "ct": ContentType.objects.get_for_model(Progetto).pk}


def test_crea_l_area_dal_progetto(client, s, p):
    pagina = client.get(f"/progetti/progetti/{p['progetto'].pk}/").content.decode()
    assert "Crea un&#x27;area di lavoro" in pagina or "Crea un'area di lavoro" in pagina
    r = client.post(reverse("ai:area_da_record", args=[p["ct"], p["progetto"].pk]))
    area = ProgettoChat.objects.get(nome="Sito Rossi")
    assert r.url == reverse("ai:progetto", args=[area.pk])
    assert CollegamentoProgetto.objects.filter(progetto=area, object_id=p["progetto"].pk).exists()
    assert set(area.membri.values_list("utente__username", flat=True)) == {"bruno", "carla"}
    assert aree.corrente(s["u"], s["az"]) == area


def test_nel_record_quello_che_nasce_nell_area(client, s, p):
    client.post(reverse("ai:area_da_record", args=[p["ct"], p["progetto"].pk]))
    area = ProgettoChat.objects.get(nome="Sito Rossi")
    mia = Conversazione.objects.create(utente=s["u"], titolo="Piano del sito", progetto=area)
    documenti_chat.crea(mia, s["u"], s["az"], "Offerta tecnica", "## Pagine")
    Artifact.objects.create(conversazione=mia, utente=s["u"], azienda=s["az"], tipo="tabella", titolo="Ore per fase",
                            spec={"tipo": "tabella", "vista": "core.aziende"}, dati={})
    Conversazione.objects.create(utente=p["bruno"], titolo="Appunti privati di Bruno", progetto=area)
    Conversazione.objects.create(utente=p["carla"], titolo="Grafica condivisa", progetto=area, condivisa=True)
    pagina = client.get(f"/progetti/progetti/{p['progetto'].pk}/").content.decode()
    sezione = pagina.split('<div class="ui-card-title">Aree di lavoro</div>')[1]
    assert "Piano del sito" in sezione and "Offerta tecnica" in sezione and "Ore per fase" in sezione
    assert "Grafica condivisa" in sezione and "Appunti privati di Bruno" not in sezione
    assert "condivisa con 2 colleghi" in sezione


def test_chi_non_e_nell_area_non_ne_vede_il_contenuto(client, s, p):
    client.post(reverse("ai:area_da_record", args=[p["ct"], p["progetto"].pk]))
    area = ProgettoChat.objects.get(nome="Sito Rossi")
    Conversazione.objects.create(utente=s["u"], titolo="Riservata", progetto=area, condivisa=True)
    estraneo = _utente("dario", s["az"])
    from django.contrib.auth.models import Permission
    estraneo.user_permissions.add(*Permission.objects.filter(content_type__app_label="progetti"))
    client.force_login(estraneo)
    pagina = client.get(f"/progetti/progetti/{p['progetto'].pk}/").content.decode()
    assert "Riservata" not in pagina and "Sito Rossi</a>" not in pagina.split('<div class="ui-card-title">Aree di lavoro</div>')[-1]
