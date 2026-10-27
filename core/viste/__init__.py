from . import registry
from .base import ModelView

register = registry.register

__all__ = ["ModelView", "register", "registry"]
