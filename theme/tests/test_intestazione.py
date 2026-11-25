"""Il nome del prodotto nell'intestazione: senza la versione (che sta in piccolo nel piè di pagina e nella pagina di
accesso) e sempre su una riga, anche con la barra piena di voci."""
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import User

from .test_base import _render

CSS = (Path(__file__).resolve().parents[1] / "static" / "theme" / "ui.css").read_text()


def _regola(selettore):
    """Le dichiarazioni della regola con quel selettore a inizio riga: quella di base, non quelle per il telefono."""
    return re.search(r"^" + re.escape(selettore) + r"\s*\{([^}]*)\}", CSS, re.M).group(1)


@pytest.mark.django_db
def test_il_nome_del_prodotto_non_porta_la_versione():
    """«Adabox v3» nell'intestazione andava a capo appena la barra si riempiva: la versione non fa parte del nome."""
    html = _render(User.objects.create_user("mario", password="pass12345!"))
    marchio, versione = settings.THEME["brand"], settings.THEME["version"]
    assert not re.search(r"\bv\d", marchio)
    assert f'<span class="ui-logo-nome">{marchio}</span>' in html
    assert f'<span class="ui-footer-version ui-code">{versione}</span>' in html and versione == "v3"


@pytest.mark.django_db
def test_la_versione_resta_nella_pagina_di_accesso(client):
    assert f"versione {settings.THEME['version']}" in client.get("/accounts/login/").content.decode()


def test_il_nome_nell_intestazione_non_va_a_capo_e_non_si_stringe():
    logo = _regola(".ui-logo")
    assert "white-space: nowrap" in logo and "flex: none" in logo
    assert "text-overflow: ellipsis" in _regola(".ui-logo-nome")


def test_con_la_barra_piena_cedono_la_ricerca_e_il_nome_della_persona():
    """Prima si stringe la ricerca (fino a un minimo), poi si tronca il nome; l'iniziale e la freccia restano intere."""
    ricerca = _regola(".ui-cerca-globale")
    assert re.search(r"flex:\s*0\s+\d+\s+180px", ricerca) and "min-width: 110px" in ricerca
    assert "width: 100%" in _regola(".ui-cerca-globale .ui-input")
    assert "text-overflow: ellipsis" in _regola(".ui-profile-name") and "min-width: 0" in _regola(".ui-profile")
    assert "flex: none" in _regola(".ui-profile-trigger .ui-avatar, .ui-profile-trigger .chev")
