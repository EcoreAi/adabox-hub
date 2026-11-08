"""AI-08: «Scrivi con Ada» in ogni campo di testo dei form e nel composer del chatter (istruzione, contesto del record
solo se visibile), e «Riassumi con Ada» nel dettaglio dei record. Il modello è finto: si guarda che cosa gli arriva."""
import json

import pytest
from django.contrib.auth.models import Permission, User
from django.urls import reverse

from ai import aiuto_testi
from core import chatter
from core.generici import ct_di
from core.models import Azienda


@pytest.fixture
def scena(db, superuser, monkeypatch):
    chiamate = []

    def finto(conversazione, corpo, utente, azienda, **kw):
        chiamate.append({"corpo": corpo, "nota": kw.get("nota"), "utente": utente})
        from ai.models import Turno
        return Turno.objects.create(conversazione=conversazione, utente=utente, compito=kw.get("compito", ""))
    monkeypatch.setattr("ai.motore.avvia", finto)
    acme = Azienda.objects.create(nome="Acme", partita_iva="01", citta="Roma")
    chatter.scrivi(acme, superuser, "Il cliente vuole la consegna entro venerdì", tipo="nota")
    return {"acme": acme, "chiamate": chiamate}


def test_campo_libero_con_istruzione_e_record(client, superuser, scena):
    acme = scena["acme"]
    r = client.post(reverse("ai:scrivi_con_ada", args=["libero"]), {
        "testo": "ciao confermo", "istruzione": "formale", "etichetta": "Messaggio", "record": f"{ct_di(acme).pk}:{acme.pk}"})
    assert r.status_code == 200 and "esito" in r.json()
    (c,) = scena["chiamate"]
    assert aiuto_testi.ISTRUZIONI_RAPIDE["formale"] in c["corpo"] and "ciao confermo" in c["corpo"]
    assert "Acme" in c["corpo"] and "consegna entro venerdì" in c["corpo"] and "Campo: Messaggio" in c["corpo"]


def test_il_record_entra_solo_se_si_vede(client, scena):
    acme = scena["acme"]
    curioso = User.objects.create_user("curioso", "c@example.com", "x")
    curioso.user_permissions.add(Permission.objects.get(codename="add_conversazione"))
    client.force_login(curioso)
    client.post(reverse("ai:scrivi_con_ada", args=["libero"]), {"testo": "", "istruzione": "scrivi un saluto",
                                                               "record": f"{ct_di(acme).pk}:{acme.pk}"})
    (c,) = scena["chiamate"]
    assert "Acme" not in c["corpo"] and "Il campo è vuoto" in c["corpo"]
    assert client.post(reverse("ai:riassumi_record", args=[ct_di(acme).pk, acme.pk])).status_code in (403, 404)


def test_riassunto_del_record(client, scena):
    acme = scena["acme"]
    html = client.get(f"/core/aziende/{acme.pk}/").content.decode()
    assert "Riassumi con Ada" in html and reverse("ai:riassumi_record", args=[ct_di(acme).pk, acme.pk]) in html
    assert 'data-scrivi-con-ada="libero"' in html                                # anche il composer del chatter
    r = client.post(reverse("ai:riassumi_record", args=[ct_di(acme).pk, acme.pk]))
    assert r.status_code == 200
    (c,) = scena["chiamate"]
    assert "Acme" in c["corpo"] and "Roma" in c["corpo"] and "consegna entro venerdì" in c["corpo"] and "Riassumi" in c["nota"]


def test_i_form_delle_viste_hanno_il_riferimento(client, scena):
    html = client.get(f"/core/aziende/{scena['acme'].pk}/modifica/").content.decode()
    assert f'data-record="{ct_di(scena["acme"]).pk}:{scena["acme"].pk}"' in html and "scrivi_con_ada.js" in html
    assert json.loads(html.split('id="ai-scrivi-campi"', 1)[1].split('>', 1)[1].split("</script>", 1)[0])["libero"] == {"domande": []}
