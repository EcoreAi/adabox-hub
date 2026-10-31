import hashlib
import json

import pytest
from django.contrib.auth.models import User

from awf import fabbrica, lavori
from awf.models import Agente, Collegamento
from core import attivita as core_attivita
from core.models import Azienda, Lavoro, TipoAttivita
from todo.models import Attivita

from .conftest import AGENTI, ingaggio

CODICE = "wfc_" + "a" * 32


def test_collegamento_dalla_pagina(client, superuser, finta, ammesse):
    finta.risposte["/api/plugins/connect"] = (201, {"install_id": "ins_1", "token": "wpt_" + "t" * 40,
                                                    "engagement": ingaggio()})
    r = client.post("/awf/stato/", {"azione": "collega", "codice": CODICE, "forge_url": "https://fabbrica.esempio.it/",
                                    "base_url": "https://erp.esempio.it", "azienda": 1})
    pagina = r.content.decode()
    assert r.status_code == 200 and "no-store" in r.get("Cache-Control", "")
    bearer = next(p for p in pagina.split("<code>") if p.startswith("awf_")).split("</code>")[0]
    assert "https://erp.esempio.it/awf/mcp/" in pagina

    richiesta = finta.richieste[0]
    assert richiesta["url"] == "https://fabbrica.esempio.it/api/plugins/connect"
    corpo = richiesta["corpo"]
    assert corpo["code"] == CODICE and corpo["kind"] == "django" and corpo["base_url"] == "https://erp.esempio.it"
    assert corpo["version"].startswith("1.0.0+")
    operazioni = {o["name"]: o for o in corpo["operations"]}
    assert operazioni["modifica_record"]["effect"] == "write" and operazioni["modifica_record"]["risk"] == "medium"
    assert operazioni["cerca_record"]["effect"] == "read"
    assert set(operazioni["modifica_record"]) == {"name", "description", "effect", "risk", "external_content",
                                                  "params_schema"}

    c = Collegamento.attuale()
    assert c.collegato and c.token() == "wpt_" + "t" * 40 and "wpt_" not in c.token_cifrato
    assert c.mcp_impronta == hashlib.sha256(bearer.encode()).hexdigest() and bearer not in str(c.__dict__)
    assert c.azienda_id == 1 and c.install_id == "ins_1"
    assert {a.nome for a in Agente.objects.all()} == {a["name"] for a in AGENTI}
    # il bearer non torna più: la pagina successiva mostra solo l'inizio
    finta.risposte["/api/plugins/heartbeat"] = (200, {"engagement": ingaggio()})
    assert bearer not in client.get("/awf/stato/").content.decode()
    # e vale per il server MCP
    r = client.post("/awf/mcp/", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {bearer}")
    assert r.status_code == 200


@pytest.mark.parametrize("stato,messaggio", [(404, "sconosciuto o scaduto"), (409, "già usato"), (500, "inattesa")])
def test_collegamento_rifiutato(client, superuser, finta, stato, messaggio):
    finta.risposte["/api/plugins/connect"] = (stato, {"detail": "no"})
    r = client.post("/awf/stato/", {"azione": "collega", "codice": CODICE, "forge_url": "https://f.esempio.it",
                                    "base_url": "https://erp.esempio.it"}, follow=True)
    assert messaggio in r.content.decode() and not Collegamento.attuale().collegato


def test_codice_e_indirizzi_controllati(finta, db):
    with pytest.raises(fabbrica.ErroreFabbrica):
        fabbrica.collega("wfc_corto", "https://f.esempio.it", "https://erp.esempio.it")
    with pytest.raises(fabbrica.ErroreFabbrica):
        fabbrica.collega(CODICE, "ftp://f.esempio.it", "https://erp.esempio.it")
    assert finta.richieste == []


def test_rigenera_bearer(client, superuser, collegato):
    vecchia = collegato.mcp_impronta
    pagina = client.post("/awf/stato/", {"azione": "rigenera"}).content.decode()
    assert Collegamento.attuale().mcp_impronta != vecchia and "Da copiare ora" in pagina


def test_battito_aggiorna_stato_e_agenti(collegato, finta):
    finta.risposte["/api/plugins/heartbeat"] = (200, {"engagement": ingaggio(
        status="paused", agents=[{"name": "Buyer"}, {"name": "Contabile", "role": "contabilità"}])})
    assert "paused" in lavori.battito()
    richiesta = finta.richieste[0]
    assert richiesta["intestazioni"]["Authorization"] == "Bearer wpt_token-della-fabbrica"
    assert richiesta["corpo"]["version"].startswith("1.0.0+")
    c = Collegamento.attuale()
    assert c.ingaggio["status"] == "paused" and c.ultimo_errore == ""
    assert User.objects.filter(username="awf-contabile").exists()
    assert not Agente.objects.get(nome="Magazziniere").attivo


def test_battito_non_riuscito_lascia_l_ultimo_stato(collegato, finta):
    finta.risposte["/api/plugins/heartbeat"] = (fabbrica.ErroreFabbrica("fabbrica non raggiungibile (URLError)"), {})
    assert "non riuscito" in lavori.battito()
    c = Collegamento.attuale()
    assert c.ingaggio["status"] == "active" and "non raggiungibile" in c.ultimo_errore
    finta.risposte["/api/plugins/heartbeat"] = (401, {})
    assert "token" in lavori.battito()


def test_pagina_di_stato(client, superuser, collegato, finta):
    finta.risposte["/api/plugins/heartbeat"] = (200, {"engagement": ingaggio(
        blocked={"code": "credit_exhausted", "detail": "credito finito"})})
    pagina = client.get("/awf/stato/").content.decode()
    assert "credit_exhausted" in pagina and "scritture ferme" in pagina and "5 giorni rimasti" in pagina
    assert "https://agate.esempio.it/console/engagements/eng_1/" in pagina
    for url in ("/awf/agenti/", "/awf/operazioni/", "/awf/approvazioni/"):
        assert client.get(url).status_code == 200


def test_pagine_solo_per_amministratori(client, utente):
    client.force_login(utente)
    for url in ("/awf/stato/", "/awf/agenti/", "/awf/operazioni/", "/awf/approvazioni/"):
        assert client.get(url).status_code == 403


def test_operazioni_dalla_pagina(client, superuser, collegato):
    client.post("/awf/operazioni/", {"azione": "aggiungi", "strumento": "modifica_record", "vista": "todo.attivita"})
    client.post("/awf/operazioni/", {"azione": "aggiungi", "strumento": "chiedi_esperto"})           # escluso
    client.post("/awf/operazioni/", {"azione": "aggiungi", "strumento": "cerca_record", "vista": "awf.qualcosa"})
    from awf.models import OperazioneAmmessa
    assert list(OperazioneAmmessa.objects.values_list("strumento", "vista")) == [("modifica_record", "todo.attivita")]
    assert User.objects.get(username="awf-buyer").has_perm("todo.change_attivita")


# ---------- eventi: solo nomi e id ----------

def _eventi(finta):
    return [r for r in finta.richieste if r["url"].endswith("/api/plugins/events")]


def test_assegnazione_a_un_agente_manda_solo_id(collegato, finta, django_capture_on_commit_callbacks):
    finta.risposte["/api/plugins/events"] = (202, {"accepted": True, "job_id": "job_1"})
    buyer = User.objects.get(username="awf-buyer")
    persona = User.objects.create_user("mario", "mario@example.com", "x")
    with django_capture_on_commit_callbacks(execute=True):
        a = Attivita.objects.create(titolo="Testo riservato del cliente", descrizione="Dettagli privati",
                                    azienda=Azienda.objects.get(pk=1), assegnatario=persona)
    assert _eventi(finta) == []                                       # assegnata a una persona: niente
    with django_capture_on_commit_callbacks(execute=True):
        a.assegnatario = buyer
        a.save()
    with django_capture_on_commit_callbacks(execute=True):
        a.titolo = "Altro testo"
        a.save()                                                      # stesso assegnatario: niente di nuovo
    eventi = _eventi(finta)
    assert len(eventi) == 1
    assert eventi[0]["corpo"] == {"type": "record.assigned", "model": "todo.attivita", "record_id": a.pk,
                                  "agent": "Buyer"}
    grezzo = eventi[0]["grezzo"].decode()
    assert "riservato" not in grezzo and "privati" not in grezzo
    assert eventi[0]["intestazioni"]["Authorization"] == "Bearer wpt_token-della-fabbrica"


def test_attivita_del_kernel_assegnata_a_un_agente(collegato, finta, django_capture_on_commit_callbacks):
    finta.risposte["/api/plugins/events"] = (202, {"accepted": True})
    record = Attivita.objects.create(titolo="Ordine", azienda=Azienda.objects.get(pk=1))
    tipo = TipoAttivita.objects.first() or TipoAttivita.objects.create(nome="Da fare")
    with django_capture_on_commit_callbacks(execute=True):
        core_attivita.pianifica(record, tipo, User.objects.get(username="awf-magazziniere"),
                                riepilogo="Chiamare il fornitore Rossi")
    corpo = _eventi(finta)[0]["corpo"]
    assert corpo == {"type": "record.assigned", "model": "todo.attivita", "record_id": record.pk,
                     "agent": "Magazziniere"}
    assert "Rossi" not in json.dumps(corpo)


def test_fabbrica_giu_non_rompe_il_salvataggio(collegato, finta, django_capture_on_commit_callbacks):
    finta.risposte["/api/plugins/events"] = (fabbrica.ErroreFabbrica("fabbrica non raggiungibile (URLError)"), {})
    with django_capture_on_commit_callbacks(execute=True):
        a = Attivita.objects.create(titolo="Ordine", azienda=Azienda.objects.get(pk=1),
                                    assegnatario=User.objects.get(username="awf-buyer"))
    assert Attivita.objects.filter(pk=a.pk).exists()
    assert Lavoro.objects.get(funzione="awf.eventi.invia").stato == Lavoro.FALLITO
    finta.risposte["/api/plugins/events"] = (429, {"detail": "troppi"})
    with django_capture_on_commit_callbacks(execute=True):
        Attivita.objects.create(titolo="Altro", azienda=Azienda.objects.get(pk=1),
                                assegnatario=User.objects.get(username="awf-buyer"))
    assert Attivita.objects.count() == 2


def test_evento_rifiuta_testo():
    with pytest.raises(ValueError):
        fabbrica.evento("record.assigned", "todo.attivita", "un testo lungo con spazi")
    with pytest.raises(ValueError):
        fabbrica.evento("record.assigned", "Testo Libero!", 1)
    with pytest.raises(ValueError):
        fabbrica.evento("altro", "todo.attivita", 1)
