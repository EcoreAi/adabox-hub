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


def test_ogni_hooks_py_e_dichiarato_nel_manifest():
    """Un hooks.py che il manifest non dichiara non viene mai chiamato (post_install, demo...)."""
    import ast
    from django.conf import settings
    addons = Path(settings.ADDONS_DIR)
    dimenticati = []
    for cartella in sorted(p for p in addons.iterdir() if (p / "__manifest__.py").is_file()):
        if (cartella / "hooks.py").is_file():
            manifest = ast.literal_eval((cartella / "__manifest__.py").read_text())
            if manifest.get("hooks") != f"{cartella.name}.hooks":
                dimenticati.append(cartella.name)
    assert dimenticati == []
