"""Smoke tests for Phase 1 / T1.

These exist only to give ``pytest`` a non-empty collection (otherwise exit
code 5 fails CI). They verify the package is importable and exposes a
sensible version. As real modules land in Phase 1 (T2+), these tests stay
as the floor of the suite.
"""

from __future__ import annotations

import importlib

from project_ghost import __version__
from project_ghost.hal import HAL_PROTOCOL_VERSION


def test_package_imports() -> None:
    """The top-level package must be importable."""
    module = importlib.import_module("project_ghost")
    assert hasattr(module, "__version__")


def test_version_is_pep440_ish() -> None:
    """Version string is a simple dotted form (Phase 0 placeholder)."""
    assert isinstance(__version__, str)
    parts = __version__.split(".")
    assert len(parts) >= 2
    allowed_extra = ("-", "a", "b", "rc")
    assert all(p.isdigit() or any(tag in p for tag in allowed_extra) for p in parts)


def test_hal_protocol_version_is_int() -> None:
    """The HAL protocol version is a stable integer constant (ADR-0004)."""
    assert isinstance(HAL_PROTOCOL_VERSION, int)
    assert HAL_PROTOCOL_VERSION >= 1
