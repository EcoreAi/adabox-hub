import hashlib
import hmac
import json
import time

import pytest

from awf.models import Approvazione, Collegamento
from core import cifratura

SEGRETO = "whsec_segreto-di-prova"


def firma_agate(segreto, corpo, t):
    """Lo stesso calcolo di agategw.contracts.webhooks.sign, scritto qui di nuovo."""
    return f"t={t},v1={hmac.new(segreto.encode(), f'{t}.'.encode() + corpo, hashlib.sha256).hexdigest()}"


@pytest.fixture
def con_segreto(collegato):
    Collegamento.objects.filter(pk=1).update(segreto_webhook_cifrato=cifratura.cifra(SEGRETO))


def manda(client, evento, t=None, segreto=SEGRETO, firma=None):
    corpo = json.dumps(evento).encode()
    t = int(time.time()) if t is None else t
    return client.post("/awf/agate-webhook/", corpo, content_type="application/json",
                       HTTP_X_AGATE_SIGNATURE=firma or firma_agate(segreto, corpo, t))


RICHIESTA = {"id": "evt_1", "type": "approval.requested", "created_at": "2026-10-31T10:00:00+00:00",
             "environment": "production",
             "data": {"approval_id": "apr_123", "tool": "adabox.modifica_record",
                      "expires_at": "2026-11-01T10:00:00+00:00", "summary": "adabox.modifica_record. Motivi: soglia"}}


def test_richiesta_e_decisione(client, con_segreto, superuser):
    assert manda(client, RICHIESTA).status_code == 200
    a = Approvazione.objects.get(approval_id="apr_123")
    assert a.stato == "in_attesa" and a.riepilogo.startswith("adabox.modifica_record") and a.scade is not None
    assert manda(client, RICHIESTA).status_code == 200 and Approvazione.objects.count() == 1      # ripetuta
    pagina = client.get("/awf/approvazioni/").content.decode()
    assert "https://agate.esempio.it/console/approvals/apr_123/" in pagina and "Motivi: soglia" in pagina
    decisa = {"type": "approval.decided", "data": {"approval_id": "apr_123", "decision": "approved"}}
    assert manda(client, decisa).status_code == 200
    a.refresh_from_db()
    assert a.stato == "approved" and a.decisa is not None
    manda(client, RICHIESTA)                                     # una consegna in ritardo non la riapre
    a.refresh_from_db()
    assert a.stato == "approved"
    assert "apr_123/" not in client.get("/awf/approvazioni/").content.decode().split("Decise di recente")[0]


def test_firma_sbagliata_o_scaduta_rifiutata(client, con_segreto):
    assert manda(client, RICHIESTA, segreto="whsec_altro").status_code == 401
    assert manda(client, RICHIESTA, t=int(time.time()) - 600).status_code == 401                 # oltre 5 minuti
    assert manda(client, RICHIESTA, firma="t=abc,v1=00").status_code == 401
    assert manda(client, RICHIESTA, firma="v1=ààà,t=1").status_code == 401
    r = client.post("/awf/agate-webhook/", json.dumps(RICHIESTA), content_type="application/json")
    assert r.status_code == 401
    assert not Approvazione.objects.exists()


def test_firma_entro_la_tolleranza(client, con_segreto):
    assert manda(client, RICHIESTA, t=int(time.time()) - 200).status_code == 200


def test_senza_segreto_503(client, collegato):
    assert manda(client, RICHIESTA).status_code == 503


def test_verifica_come_agate():
    from awf import webhook
    corpo = b'{"a": 1}'
    assert webhook.firma(SEGRETO, corpo, t=1000) == firma_agate(SEGRETO, corpo, 1000)
    assert webhook.verifica(SEGRETO, firma_agate(SEGRETO, corpo, 1000), corpo, ora=1100) == 1000
    with pytest.raises(webhook.FirmaNonValida):
        webhook.verifica(SEGRETO, firma_agate(SEGRETO, corpo, 1000), corpo + b" ", ora=1100)
