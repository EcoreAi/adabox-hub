"""Intestazioni di sicurezza del kernel: niente DNS prefetch, Content-Security-Policy in sola segnalazione con il suo
indirizzo per le segnalazioni, e l'avvio che si ferma con la SECRET_KEY di sviluppo."""
import json
import logging

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError


def test_ogni_pagina_dice_al_browser_che_cosa_segnalare(client, superuser, settings):
    r = client.get("/dashboard/")
    assert r["X-DNS-Prefetch-Control"] == "off" and "Content-Security-Policy" not in r        # non blocca nulla
    politica = r["Content-Security-Policy-Report-Only"]
    assert "script-src 'self'" in politica and "object-src 'none'" in politica and "report-uri /csp/segnalazione/" in politica
    settings.CSP_SOLO_SEGNALAZIONE = False
    r = client.get("/dashboard/")
    assert "Content-Security-Policy-Report-Only" not in r and r["X-DNS-Prefetch-Control"] == "off"


def test_le_segnalazioni_finiscono_nel_log_una_volta_per_violazione(client, db, caplog):
    cache.clear()
    corpo = json.dumps({"csp-report": {"document-uri": "https://hub.example/ai/chat/7/?token=segreto", "effective-directive": "script-src",
                                       "blocked-uri": "https://cdn.example/libreria.js?x=1"}})
    with caplog.at_level(logging.WARNING, logger="sicurezza.csp"):
        for _ in range(3):
            assert client.post("/csp/segnalazione/", corpo, content_type="application/csp-report").status_code == 204
    righe = [r.getMessage() for r in caplog.records if r.name == "sicurezza.csp"]
    assert len(righe) == 1 and "script-src" in righe[0] and "https://cdn.example/libreria.js" in righe[0]
    assert "segreto" not in righe[0] and "x=1" not in righe[0]                                # mai i parametri degli indirizzi
    assert client.post("/csp/segnalazione/", "non json", content_type="application/csp-report").status_code == 400
    assert client.post("/csp/segnalazione/", "x" * 20000, content_type="application/csp-report").status_code == 413
    assert client.get("/csp/segnalazione/").status_code == 405
    cache.clear()


def test_l_avvio_si_ferma_con_la_chiave_di_sviluppo(settings):
    settings.DEBUG, settings.SECRET_KEY = False, settings.CHIAVE_DI_SVILUPPO
    with pytest.raises(CommandError, match="SECRET_KEY"):
        call_command("controlla_avvio")
    settings.DEBUG = True
    call_command("controlla_avvio")                                  # in sviluppo si lavora anche così
    settings.DEBUG, settings.SECRET_KEY = False, "una-chiave-casuale-lunga-di-questa-istanza"
    call_command("controlla_avvio")
