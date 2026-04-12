"""Talos Common — shared library for Talos CleanRoom applications.

Each app (Deployment Console, Scanning Console, Portal) calls
``talos_common.init(get_settings)`` at startup to register its
settings getter.  All shared modules then use ``talos_common.get_settings``
as a FastAPI dependency.
"""

from typing import Callable, Any

__version__ = "0.1.0"

_settings_getter: Callable[[], Any] | None = None


def init(settings_getter: Callable[[], Any]) -> None:
    """Register the application's settings getter.

    Must be called once during app startup before any shared router
    or dependency that needs settings is invoked.

    Args:
        settings_getter: A callable (typically the app's ``get_settings``)
            that returns a ``BaseAppSettings`` subclass instance.
    """
    global _settings_getter
    _settings_getter = settings_getter


def get_settings():
    """FastAPI-compatible dependency that returns the app's settings.

    Raises ``RuntimeError`` if ``init()`` has not been called.
    """
    if _settings_getter is None:
        raise RuntimeError(
            "talos_common not initialized. "
            "Call talos_common.init(get_settings) during app startup."
        )
    return _settings_getter()
