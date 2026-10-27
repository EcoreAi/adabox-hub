import textwrap

import pytest
from django.contrib.auth.models import User


@pytest.fixture
def utente(db):
    return User.objects.create_user("mario", "mario@example.com", "pass12345!")


@pytest.fixture
def staff(db, client):
    u = User.objects.create_user("staff", "staff@example.com", "pass12345!", is_staff=True)
    client.force_login(u)
    return u


@pytest.fixture
def superuser(db, client):
    u = User.objects.create_superuser("root", "root@example.com", "pass12345!")
    client.force_login(u)
    return u


class _Addons:
    """Cartella addons temporanea con una factory di moduli finti (manifest, apps, models, migrations)."""

    def __init__(self, cartella):
        self.dir = cartella

    def crea(self, slug, modelli="", **extra):
        manifest = {"name": slug.title(), "version": "1.0.0", "min_core": "1.0", **extra}
        d = self.dir / slug
        (d / "migrations").mkdir(parents=True)
        (d / "migrations" / "__init__.py").write_text("")
        (d / "__init__.py").write_text("")
        (d / "__manifest__.py").write_text(repr(manifest))
        (d / "apps.py").write_text(textwrap.dedent(f"""
            from django.apps import AppConfig


            class Config(AppConfig):
                name = "{slug}"
        """))
        (d / "models.py").write_text("from django.db import models\n" + textwrap.dedent(modelli))
        return d


@pytest.fixture
def addons_tmp(tmp_path, settings, monkeypatch):
    cartella = tmp_path / "addons"
    cartella.mkdir()
    settings.ADDONS_DIR = cartella
    monkeypatch.syspath_prepend(str(cartella))
    return _Addons(cartella)


def pytest_collection_modifyitems(config, items):
    """I test marcati postgres (concorrenza reale) girano solo su Postgres: deploy/test-postgres.sh."""
    from django.db import connection
    if connection.vendor == "postgresql":
        return
    salta = pytest.mark.skip(reason="solo su Postgres (deploy/test-postgres.sh)")
    for item in items:
        if "postgres" in item.keywords:
            item.add_marker(salta)
