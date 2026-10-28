"""Tutti i sorgenti del progetto compilano senza SyntaxWarning (es. sequenze di escape non valide nelle stringhe)."""
import warnings
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]


def test_nessun_syntax_warning():
    problemi = []
    for p in RADICE.rglob("*.py"):
        if {".venv", ".git", "node_modules"} & set(p.parts):
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            try:
                compile(p.read_text(encoding="utf-8"), str(p), "exec")
            except (SyntaxError, SyntaxWarning) as e:
                problemi.append(f"{p.relative_to(RADICE)}: {e}")
    assert problemi == []
