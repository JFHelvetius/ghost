"""Tests del `Handle` (frozen dataclass devuelto por `schedule*`).

`Handle` es un wrapper trivial pero su contrato (frozen, `cancel`
nunca lanza) tiene que ser explícito.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from project_ghost.core.clock import Handle


def test_handle_is_frozen() -> None:
    h = Handle(cancel=lambda: None)
    with pytest.raises(FrozenInstanceError):
        h.cancel = lambda: None  # type: ignore[misc]


def test_handle_cancel_is_called() -> None:
    calls: list[int] = []
    h = Handle(cancel=lambda: calls.append(1))
    h.cancel()
    assert calls == [1]


def test_handle_cancel_can_be_called_multiple_times_without_raising() -> None:
    """Idempotencia del wrapper: invocar `cancel()` varias veces no debe
    lanzar. La idempotencia real (efecto único) la garantiza el caller
    (en `SimClockImpl` mediante un token compartido)."""
    calls: list[int] = []
    h = Handle(cancel=lambda: calls.append(1))
    h.cancel()
    h.cancel()
    h.cancel()
    assert len(calls) == 3  # el wrapper no dedupea; el caller sí
