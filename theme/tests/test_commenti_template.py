import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]


def test_nessun_commento_template_su_piu_righe():
    """`{# … #}` vale solo su una riga: su più righe Django lo stampa nella pagina. Per i commenti lunghi c'è
    {% comment %} … {% endcomment %}."""
    colpevoli = []
    for p in RADICE.rglob("templates/**/*.html"):
        if ".git" in p.parts or "node_modules" in p.parts:
            continue
        testo = p.read_text(errors="replace")
        for m in re.finditer(r"\{#", testo):
            if "#}" not in testo[m.start():].split("\n", 1)[0]:
                colpevoli.append(f"{p.relative_to(RADICE)}:{testo[:m.start()].count(chr(10)) + 1}")
    assert colpevoli == []
