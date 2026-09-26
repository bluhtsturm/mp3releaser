"""Weboberflaeche - dieselbe Dienstschicht, nur ueber HTTP.

Laesst sich auch ohne FastAPI importieren; ``is_available()`` sagt, ob die
Abhaengigkeiten da sind.
"""

from .app import create_app, is_available, requirements_hint, run

__all__ = ["create_app", "run", "is_available", "requirements_hint"]
