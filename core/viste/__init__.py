from . import registry
from .base import ModelView
from .righe import Inline

register = registry.register

__all__ = ["Inline", "ModelView", "register", "registry"]
