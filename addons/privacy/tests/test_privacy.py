"""LOC-07: consensi con storico, esportazione dei dati di un contatto, anonimizzazione che preserva i documenti fiscali,
regole di conservazione eseguite dal cron, richieste con scadenza a 30 giorni."""
import datetime
import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

import privacy
from contatti.models import Contatto, IndirizzoContatto
from core import chatter
from core.models import Azienda, EmailRicevuta, RegistroModifica
from privacy import servizi
from privacy.models import Anonimizzazione, Consenso, Finalita, RegolaConservazione, RichiestaInteressato


@pytest.fixture
def s(db, superuser):
    call_command("loaddata", str(Path(privacy.__file__).parent / "data" / "finalita.json"), verbosity=0)
    az = Azienda.objects.get(pk=1)
    mario = Contatto.objects.create(azienda=az, tipo="persona", nome="Mario Rossi", email="mario@rossi.it", telefono="333 111",
                                    codice_fiscale="RSSMRA80A01H501U", indirizzo="Via Roma 1", citta="Roma", note="cliente storico")
    IndirizzoContatto.objects.create(azienda=az, contatto=mario, tipo="consegna", indirizzo="Via Magazzino 2", citta="Roma")
    return {"az": az, "mario": mario, "news": Finalita.objects.get(pk=1), "io": superuser}


def test_consensi_con_storico(client, s):
    url = reverse("privacy:consenso", args=[s["mario"].pk])
    client.post(url, {"finalita": s["news"].pk, "dato": "1", "fonte": "modulo"})
    assert servizi.ha_consenso(s["mario"], s["news"])
    client.post(url, {"finalita": s["news"].pk, "dato": "0", "fonte": "email"})
    assert not servizi.ha_consenso(s["mario"], s["news"]) and Consenso.objects.count() == 2       # la prova resta
    html = client.get(f"/contatti/contatti/{s['mario'].pk}/").content.decode()
    assert "Comunicazioni commerciali e newsletter" in html and "Revocato il" in html and "Esporta i dati" in html
    assert "consenso" in chatter.messaggi_di(s["mario"]).first().corpo.lower()


def test_esportazione(client, s):
    servizi.registra(s["mario"], s["news"], True, "modulo", s["io"])
    r = client.get(reverse("privacy:esporta", args=[s["mario"].pk]))
    assert r.status_code == 200 and r["Content-Disposition"].endswith('.json"')
    dati = json.loads(r.content)
    assert dati["contatto"]["dati"]["email"] == "mario@rossi.it" and dati["consensi"][0]["dato"] is True
    assert any("Via Magazzino 2" in json.dumps(v) for v in dati["collegati"].values())


def test_anonimizzazione_completa_senza_documenti(client, s):
    mario = s["mario"]
    mario.telefono = "333 999"
    mario.save()                                           # una voce nel registro con i valori vecchi
    servizi.registra(mario, s["news"], True, "modulo", s["io"])
    chatter.scrivi(mario, s["io"], "Mario ha chiamato dal 333 111", tipo="nota")
    assert client.get(reverse("privacy:anonimizza", args=[mario.pk])).status_code == 200
    client.post(reverse("privacy:anonimizza", args=[mario.pk]), {"conferma": "no"})
    assert not Anonimizzazione.objects.exists()
    client.post(reverse("privacy:anonimizza", args=[mario.pk]), {"conferma": "anonimizza"})
    mario.refresh_from_db()
    assert mario.nome.startswith("Contatto anonimizzato") and not mario.email and not mario.codice_fiscale and not mario.attivo
    assert not mario.indirizzi.exists() and not servizi.ha_consenso(mario, s["news"])
    assert not Anonimizzazione.objects.get().parziale
    assert "333" not in json.dumps(list(RegistroModifica.objects.filter(object_id=mario.pk).values_list("modifiche", flat=True)))
    assert all("333 111" not in (m.corpo or "") for m in chatter.messaggi_di(mario))


def test_anonimizzazione_parziale_con_documenti_fiscali(s):
    from django.apps import apps
    if not apps.is_installed("vendite"):
        pytest.skip("vendite non installato")
    from vendite.models import OrdineVendita
    rossi = Contatto.objects.create(azienda=s["az"], nome="Rossi Srl", partita_iva="12345678903", email="info@rossi.it",
                                    telefono="06 1234", indirizzo="Via Fiscale 3", citta="Roma", cliente=True)
    OrdineVendita.objects.create(azienda=s["az"], cliente=rossi)
    assert servizi.documenti_da_conservare(rossi)
    esito = servizi.anonimizza(rossi, s["io"])
    rossi.refresh_from_db()
    assert esito.parziale and rossi.nome == "Rossi Srl" and rossi.partita_iva == "12345678903" and rossi.indirizzo == "Via Fiscale 3"
    assert not rossi.email and not rossi.telefono and OrdineVendita.objects.filter(cliente=rossi).exists()
    with pytest.raises(ValueError):
        servizi.anonimizza(rossi, s["io"])


def test_opportunita_perdono_email_e_nome_copiati(s):
    from django.apps import apps
    if not apps.is_installed("crm"):
        pytest.skip("crm non installato")
    from crm.models import FaseCrm, Opportunita
    fase = FaseCrm.objects.first() or FaseCrm.objects.create(nome="Nuova")
    o = Opportunita.objects.create(azienda=s["az"], titolo="Offerta", contatto=s["mario"], nome_contatto="Mario Rossi",
                                   email="mario@rossi.it", fase=fase)
    servizi.anonimizza(s["mario"], s["io"])
    o.refresh_from_db()
    assert o.email == "" and o.nome_contatto == "" and o.titolo == "Offerta"


def test_conservazione_dal_cron(s):
    vecchia = EmailRicevuta.objects.create(message_id="<a@x>", stato=EmailRicevuta.NON_ABBINATA)
    EmailRicevuta.objects.filter(pk=vecchia.pk).update(ricevuta=timezone.now() - datetime.timedelta(days=400))
    nuova = EmailRicevuta.objects.create(message_id="<b@x>", stato=EmailRicevuta.NON_ABBINATA)
    assert servizi.applica_conservazione() == 0                       # senza regole non si cancella niente
    RegolaConservazione.objects.create(chiave="core.email_ricevute", giorni=365)
    assert servizi.applica_conservazione() == 1
    assert list(EmailRicevuta.objects.all()) == [nuova]
    assert RegolaConservazione.objects.get().cancellati == 1


def test_le_regole_si_scelgono_solo_tra_i_dati_dichiarati(client, s):
    html = client.get("/privacy/conservazione/nuovo/").content.decode()
    assert "Email ricevute nella casella delle risposte" in html and "consigliati 365 giorni" in html
    client.post("/privacy/conservazione/nuovo/", {"chiave": "contatti.Contatto", "giorni": 1, "attiva": "on"})
    assert not RegolaConservazione.objects.exists()


def test_richiesta_con_scadenza(s):
    r = RichiestaInteressato.objects.create(azienda=s["az"], richiedente="Mario Rossi", tipo="cancellazione",
                                            ricevuta_il=datetime.date(2026, 11, 1), contatto=s["mario"])
    assert r.scadenza == datetime.date(2026, 12, 1)
