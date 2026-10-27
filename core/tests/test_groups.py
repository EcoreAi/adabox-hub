import pytest
from django.contrib.auth.models import Group, Permission

from core.registry.groups import crea_gruppi, espandi
from core.registry.manifest import Manifest


def _manifest(groups):
    return Manifest(slug="prova", percorso=None, name="Prova", version="1.0.0", min_core="1.0", groups=groups)


@pytest.mark.django_db
def test_espandi():
    tutti = espandi("core.*")
    attesi = sorted(f"core.{p.codename}" for p in Permission.objects.filter(content_type__app_label="core"))
    assert tutti == attesi and "core.view_azienda" in tutti
    assert espandi("core.view_azienda") == ["core.view_azienda"]
    with pytest.raises(ValueError):
        espandi("core.vola_azienda")


def _perms(nome):
    return sorted(f"{p.content_type.app_label}.{p.codename}" for p in Group.objects.get(name=nome).permissions.all())


@pytest.mark.django_db
def test_crea_gruppi_e_riallinea():
    nomi = crea_gruppi(_manifest({"Prova / Utente": ["core.view_azienda", "core.add_azienda"],
                                  "Prova / Capo": ["core.*"]}))
    assert nomi == ["Prova / Utente", "Prova / Capo"]
    assert _perms("Prova / Utente") == ["core.add_azienda", "core.view_azienda"]
    assert _perms("Prova / Capo") == espandi("core.*")
    crea_gruppi(_manifest({"Prova / Utente": ["core.view_azienda"]}))
    assert _perms("Prova / Utente") == ["core.view_azienda"]
