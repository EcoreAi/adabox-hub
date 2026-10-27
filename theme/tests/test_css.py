from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "static" / "theme"

# Residui di SIEE che non devono comparire nel tema generico
VIETATI = [
    "siee", "--color-", "datatable", "ridisegnata", "brand-enas", "logo-mark img",
    "form-control", "form-select", "mega", "scope", "suggest", "kv-2col",
    "back-btn", "back-link", "impianto", "quickstart", "report", "htmx", "alpine",
]

CLASSI_RICHIESTE = [
    ".ui-body", ".ui-container", ".ui-header", ".ui-logo", ".ui-logo-mark", ".ui-nav",
    ".ui-nav-toggle", ".ui-dropdown", ".ui-profile-trigger", ".ui-avatar",
    ".ui-pagehead", ".ui-kpis", ".ui-kpi", ".ui-card", ".ui-card-head", ".ui-card-body",
    ".ui-btn", ".ui-btn-primary", ".ui-btn-secondary", ".ui-btn-ghost", ".ui-btn-danger",
    ".ui-btn-sm", ".ui-icon-btn", ".ui-input", ".ui-label", ".ui-form-group",
    ".ui-pill", ".ui-pill-ok", ".ui-pill-warn", ".ui-pill-danger", ".ui-pill-neutral",
    "table.ui-table", ".ui-empty", ".ui-alert", ".ui-alert-error", ".ui-login",
    ".ui-login-card", ".ui-footer", ".ui-toast", ".ui-link", ".ui-code",
]


def test_ui_css_senza_residui_siee():
    testo = (CSS / "ui.css").read_text().lower()
    presenti = [v for v in VIETATI if v in testo]
    assert presenti == [], f"residui SIEE in ui.css: {presenti}"


def test_ui_css_ha_le_classi_del_catalogo():
    testo = (CSS / "ui.css").read_text()
    mancanti = [c for c in CLASSI_RICHIESTE if c not in testo]
    assert mancanti == [], f"classi mancanti in ui.css: {mancanti}"


def test_admin_css_senza_residui_siee():
    testo = (CSS / "admin.css").read_text().lower()
    assert "siee" not in testo
