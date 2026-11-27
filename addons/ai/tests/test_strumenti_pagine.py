"""Ada e le pagine del gestionale: cerca_pagine, la ricerca di «Cerca ovunque» per pagine, menu, grafici e dashboard,
con i link. Prima Ada sapeva che «Statistiche» c'era ma non ne aveva l'indirizzo, e lo inventava ([URL_ANALISI])."""
import json

import pytest
from django.contrib.auth.models import User

from ai import strumenti
from ai.models import Conversazione
from ai.strumenti import base
from core.models import Azienda

pytestmark = pytest.mark.django_db


def _contesto(utente):
    azienda = Azienda.objects.get(pk=1)
    return strumenti.Contesto(utente=utente, azienda=azienda, conversazione=Conversazione.objects.create(utente=utente, titolo="Pagine"))


def test_cerca_pagine_da_il_link_di_statistiche_e_del_nuovo_grafico(superuser):
    contesto = _contesto(superuser)
    trovate = base.cerca_pagine(contesto, "statistiche")["pagine"]
    assert {"titolo": "Statistiche", "url": "/grafici/", "tipo": "Pagina di Analisi"} in trovate
    assert any(p["url"] == "/grafici/costruttore/" for p in base.cerca_pagine(contesto, "nuovo grafico")["pagine"])
    assert base.cerca_pagine(contesto, "zzzqqq") == {"pagine": [], "nota": base.cerca_pagine(contesto, "zzzqqq")["nota"]}


def test_cerca_pagine_rispetta_i_permessi():
    semplice = User.objects.create_user("semplice", password="pass12345!")
    trovate = base.cerca_pagine(_contesto(semplice), "statistiche utenti")["pagine"]
    assert not any(p["url"] in ("/grafici/", "/utenti/") for p in trovate)


def test_cerca_pagine_trova_le_sezioni_delle_app(superuser):
    trovate = base.cerca_pagine(_contesto(superuser), "scadenziario")["pagine"]
    assert {"titolo": "Fatturazione › Scadenziario", "url": "/fatturazione/scadenzario/", "tipo": "Voce di menu"} in trovate


def test_app_disponibili_resta_sotto_il_limite_dei_risultati(superuser):
    """Con il link di ogni sezione passava i 20.000 caratteri e si troncava: i link li dà cerca_pagine."""
    from ai.strumenti.registro import LIMITE_RISULTATO
    assert len(json.dumps(base.app_disponibili(_contesto(superuser)), ensure_ascii=False)) < LIMITE_RISULTATO * 0.75


def test_lo_strumento_c_e_per_tutti(superuser):
    assert "cerca_pagine" in {s.nome for s in strumenti.disponibili(superuser, azienda=Azienda.objects.get(pk=1))}
