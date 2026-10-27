from pathlib import Path

ICONE = [
    "zap", "user", "lock", "tool", "chevron-down", "menu", "x", "check", "alert-triangle",
    "search", "arrow-left", "download", "log-out", "eye", "eye-off", "save", "plus",
    "edit", "trash", "inbox", "info",
]


def test_sprite_contiene_le_icone():
    html = (Path(__file__).resolve().parents[1] / "templates/theme/partials/_icons.html").read_text()
    mancanti = [i for i in ICONE if f'id="icon-{i}"' not in html]
    assert mancanti == []
    assert "siee" not in html.lower()
