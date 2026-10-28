"""Aiuti per i test dei pacchetti: un modulo finto completo in una cartella qualsiasi."""
import textwrap
from pathlib import Path


def crea_modulo(radice, slug, **extra):
    manifest = {"name": slug.title(), "version": "1.0.0", "min_core": "1.0", **extra}
    d = Path(radice) / slug
    (d / "migrations").mkdir(parents=True)
    (d / "migrations" / "__init__.py").write_text("")
    (d / "__init__.py").write_text("")
    (d / "__manifest__.py").write_text(repr(manifest))
    (d / "apps.py").write_text(textwrap.dedent(f"""
        from django.apps import AppConfig


        class Config(AppConfig):
            name = "{slug}"
    """))
    (d / "models.py").write_text("from django.db import models\n")
    return d
