"""Card e tabelle arrivate con HTMX dopo il caricamento: ui.css le tiene invisibili finché non hanno .is-revealed, e
ui.js la aggiungeva solo a quelle della pagina caricata. Una card sostituita (hx-swap="outerHTML") restava a opacity 0:
sulla dashboard, premuto un periodo, al posto del grafico un buco.

Il comportamento è provato fuori dal repository con jsdom e la htmx del tema (htmx.swap outerHTML e innerHTML): qui
si controlla che il gestore ci sia e faccia quelle cose, perché la CI non ha un DOM per eseguire ui.js."""
import re

from django.contrib.staticfiles import finders


def _ui_js():
    return open(finders.find("theme/ui.js"), encoding="utf-8").read()


def test_ui_js_rende_visibile_cio_che_arriva_con_htmx():
    js = _ui_js()
    gestore = re.search(r"addEventListener\('htmx:load', \(e\) => \{(.*?)\n  \}\);", js, re.S)
    assert gestore, "manca il gestore di htmx:load in ui.js"
    corpo = gestore.group(1)
    assert "radice === document.body" in corpo                        # il primo htmx:load è il caricamento: ci pensa già ui.js
    assert ".ui-card:not(.is-revealed)" in corpo and "classList.add('is-revealed')" in corpo
    assert "table.ui-table:not(.is-revealed)" in corpo and "forEach(reveal)" in corpo
    assert "radice.matches(sel)" in corpo                              # anche la card che è essa stessa il frammento


def test_il_gestore_sta_dopo_reveal():
    """`reveal` è una const: il gestore deve venire dopo, nello stesso blocco."""
    js = _ui_js()
    assert js.index("const reveal = ") < js.index("'htmx:load'")
