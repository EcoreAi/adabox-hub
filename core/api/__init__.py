"""API JSON del kernel: /api/v1/, sessione Django o token Bearer."""
from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI
from ninja.security import django_auth

from core import __version__

from .auth import TokenAuth

api = NinjaAPI(title="adabox-hub", version=__version__, auth=[django_auth, TokenAuth()],
               docs_decorator=login_required, urls_namespace="api")

from . import fissi, modelli  # noqa: E402,F401  (registrano i router)
