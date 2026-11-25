"""Aiuti dei test: un grafico salvato già messo in una pagina; la cascata del foglio di stile su una pagina resa."""
import re

import cssselect2
import tinycss2
import tinyhtml5
from django.contrib.staticfiles import finders

from grafici import motore
from grafici.models import Grafico


def in_pagina(pagina, **campi):
    g = Grafico.objects.create(**campi)
    motore.metti_in_pagina(pagina, g)
    pagina.refresh_from_db()
    return g


def cascata(html):
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
