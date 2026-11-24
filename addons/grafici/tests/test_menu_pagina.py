"""Il menu ⋯ di una pagina della dashboard (titolo, icona, condivisione) e il pannello «Nuova pagina».

Nell'intestazione della pagina il tema mette i form in linea (`.ui-pagehead-actions form`), e i bottoni del menu hanno
lo sfondo trasparente (`.an-menu-pannello button`): due regole che vincevano su quelle del menu. I campi finivano uno
sotto l'altro, la tendina dell'icona alta 34px tagliava il suo testo, «Salva» sembrava testo e «Crea» era bianco su
bianco. Qui si calcola la cascata vera (specificità e ordine, come un browser, senza @media: lo schermo largo) sulla
pagina resa, con i fogli di stile che la pagina carica. Non è la resa in un browser: non misura le larghezze.
"""
import re

import cssselect2
import pytest
import tinycss2
import tinyhtml5
from django.contrib.staticfiles import finders
from django.urls import reverse

from core.models import Azienda, ProfiloUtente
from grafici import motore

pytestmark = pytest.mark.django_db

TRASPARENTE = {"transparent", "none", "rgba(0,0,0,0)"}


def _cascata(html):
    """(radice della pagina, funzione che dà il valore vincente di una proprietà per un elemento)."""
    radice = cssselect2.ElementWrapper.from_html_root(tinyhtml5.parse(html, namespace_html_elements=False))
    matcher = cssselect2.Matcher()
    for href in re.findall(r'<link rel="stylesheet" href="/static/([^"?]+)', html):
        percorso = finders.find(href)
        if not percorso:
            continue
        with open(percorso, encoding="utf-8") as f:
            regole = tinycss2.parse_stylesheet(f.read(), skip_whitespace=True, skip_comments=True)
        for regola in regole:
            if regola.type != "qualified-rule":          # @import, @media, @keyframes: fuori
                continue
            dichiarazioni = {}
            for d in tinycss2.parse_declaration_list(regola.content, skip_whitespace=True, skip_comments=True):
                if d.type == "declaration":
                    dichiarazioni[d.lower_name] = (tinycss2.serialize(d.value).strip(), d.important)
            try:
                selettori = cssselect2.compile_selector_list(regola.prelude)
            except cssselect2.SelectorError:                # ::-webkit-details-marker e simili: non toccano questi elementi
                continue
            for selettore in selettori:
                if selettore.pseudo_element is None and ":hover" not in tinycss2.serialize(regola.prelude):
                    matcher.add_selector(selettore, dichiarazioni)

    def valore(elemento, proprieta, *alias):
        vincente = None
        for specificita, ordine, _, dichiarazioni in matcher.match(elemento) or []:
            for nome in (proprieta, *alias):
                if nome in dichiarazioni:
                    v, importante = dichiarazioni[nome]
                    chiave = (importante, specificita, ordine)
                    if vincente is None or chiave >= vincente[0]:
                        vincente = (chiave, nome, v)
        if vincente is None:
            return None
        _, nome, v = vincente
        if nome == "padding":                            # padding: A [B [C [D]]] -> il lato chiesto
            parti = v.split()
            parti = {1: parti * 4, 2: parti * 2, 3: [*parti, parti[1]], 4: parti}[len(parti)]
            return parti[{"padding-top": 0, "padding-bottom": 2}[proprieta]]
        return v.split()[0] if nome == "background" else v

    return radice, valore


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
