"""File statici con l'impronta del contenuto nel nome (core.storage.StaticConImpronta). Cambiare STATIC_ROOT nei test
ricrea lo storage (segnale setting_changed di Django)."""
from django.core.management import call_command
from django.templatetags.static import static


def test_con_il_manifest_l_url_ha_l_impronta_e_il_file_originale_resta(settings, tmp_path):
    settings.STATIC_IMPRONTA, settings.STATIC_ROOT = True, tmp_path
    call_command("collectstatic", "--noinput", verbosity=0)    # niente errori per le source map delle librerie
    url = static("theme/admin.css")
    assert url.startswith("/static/theme/admin.") and url.endswith(".css") and url != "/static/theme/admin.css"
    assert (tmp_path / "theme" / "admin.css").exists() and (tmp_path / url.removeprefix("/static/")).exists()
    assert static("theme/non-esiste.css") == "/static/theme/non-esiste.css"    # fuori dal manifest: l'URL di sempre
    settings.STATIC_IMPRONTA = False                                            # es. sviluppo con runserver
    assert static("theme/admin.css") == "/static/theme/admin.css"


def test_senza_manifest_gli_url_di_sempre(settings, tmp_path):
    settings.STATIC_IMPRONTA, settings.STATIC_ROOT = True, tmp_path
    assert static("theme/admin.css") == "/static/theme/admin.css"
