"""Il menu ⋯ di una pagina della dashboard (titolo, icona, condivisione) e il pannello «Nuova pagina».

Nell'intestazione della pagina il tema mette i form in linea (`.ui-pagehead-actions form`), e i bottoni del menu hanno
lo sfondo trasparente (`.an-menu-pannello button`): due regole che vincevano su quelle del menu. I campi finivano uno
sotto l'altro, la tendina dell'icona alta 34px tagliava il suo testo, «Salva» sembrava testo e «Crea» era bianco su
bianco. Qui si calcola la cascata vera (specificità e ordine, come un browser, senza @media: lo schermo largo) sulla
pagina resa, con i fogli di stile che la pagina carica. Non è la resa in un browser: non misura le larghezze.
"""
import re

import pytest
from django.urls import reverse

from core.models import Azienda, ProfiloUtente
from grafici import motore
from grafici.tests.aiuti import cascata as _cascata

pytestmark = pytest.mark.django_db

TRASPARENTE = {"transparent", "none", "rgba(0,0,0,0)"}


def _px(testo, carattere=14):
    if testo.endswith("px"):
        return float(testo[:-2])
    return float(testo) * carattere                       # line-height senza unità: un multiplo del carattere


def _uno(radice, selettore):
    trovati = list(radice.query_all(selettore))
    assert len(trovati) == 1, (selettore, len(trovati))
    return trovati[0]


@pytest.fixture
def pagina(client, superuser):
    ProfiloUtente.objects.get_or_create(utente=superuser)[0].aziende.add(Azienda.objects.get(pk=1))
    client.force_login(superuser)
    p = motore.nuova_pagina(superuser, "La mia dashboard")
    return _cascata(client.get(reverse("grafici:pagina", args=[p.pk])).content.decode())


def test_titolo_e_icona_restano_in_un_modulo_a_righe(pagina):
    radice, valore = pagina
    modulo = _uno(radice, 'form[action$="/modifica/"]')
    assert valore(modulo, "display") in {"flex", "grid"}
    assert valore(_uno(radice, 'form[action$="/sposta/"]'), "display") == "flex"
    assert valore(_uno(radice, 'form[action$="/condividi/"]'), "display") == "grid"


def test_il_testo_della_tendina_dell_icona_non_e_tagliato(pagina):
    """Con un'altezza fissa, tolti i margini interni e il bordo, deve restare la riga del testo."""
    radice, valore = pagina
    tendina = _uno(radice, 'form[action$="/modifica/"] select[name="icona"]')
    altezza = valore(tendina, "height")
    if altezza and altezza.endswith("px"):
        spazio = _px(altezza) - _px(valore(tendina, "padding-top", "padding")) - _px(valore(tendina, "padding-bottom", "padding")) - 2
        assert spazio >= _px(valore(tendina, "line-height")), (altezza, spazio)


@pytest.mark.parametrize("selettore", ['form[action$="/modifica/"] button', 'form[action$="/condividi/"] button',
                                       'form[action$="/nuova/"] button'])
def test_i_bottoni_primari_dei_menu_hanno_il_loro_sfondo(pagina, selettore):
    """«Salva», «Salva la condivisione» e «Crea» (che aveva il testo bianco: senza sfondo era invisibile)."""
    radice, valore = pagina
    bottone = _uno(radice, selettore)
    assert "ui-btn-primary" in bottone.etree_element.get("class")
    sfondo = valore(bottone, "background-color", "background")
    assert sfondo and sfondo.replace(" ", "") not in TRASPARENTE, sfondo
