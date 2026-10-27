import re
from pathlib import Path

THEME = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"^\s*(from|import)\s+(core|config)\b", re.M)


def test_theme_non_importa_core_ne_config():
    colpevoli = []
    for p in THEME.rglob("*.py"):
        if "tests" in p.parts:
            continue
        if PATTERN.search(p.read_text()):
            colpevoli.append(str(p.relative_to(THEME)))
    assert colpevoli == []


def test_template_theme_non_usano_url_di_core_senza_as():
    """`{% url 'core:x' %}` secco romperebbe un progetto senza core;
    la forma `{% url 'core:x' as var %}` è tollerata."""
    colpevoli = []
    for p in (THEME / "templates").rglob("*.html"):
        for riga in p.read_text().splitlines():
            if "{% url 'core:" in riga and " as " not in riga:
                colpevoli.append(f"{p.name}: {riga.strip()}")
    assert colpevoli == []
