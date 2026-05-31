"""Configuration package — re-exports for backward-compatible imports.

Existing code using ``from app.config import settings`` continues to work.
New code should prefer ``from app.config.settings import settings``.
"""

from app.config.settings import Settings, settings

__all__ = ["Settings", "settings"]
