"""Tests de composición de validity (uncertainty.md §6.1)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from project_ghost.core.uncertainty import Validity, compose_validity

from .strategies import validity_values


def test_compose_validity_is_min_two_inputs() -> None:
    """uncertainty.md §6.1 — composición = min sobre IntEnum."""
    assert compose_validity(Validity.VALID, Validity.DEGRADED) == Validity.DEGRADED
    assert compose_validity(Validity.STALE, Validity.VALID) == Validity.STALE
    assert compose_validity(Validity.INVALID, Validity.VALID) == Validity.INVALID
    assert compose_validity(Validity.VALID, Validity.VALID) == Validity.VALID


def test_compose_validity_three_inputs() -> None:
    out = compose_validity(Validity.VALID, Validity.DEGRADED, Validity.STALE)
    assert out == Validity.STALE


def test_compose_validity_single_input() -> None:
    assert compose_validity(Validity.DEGRADED) == Validity.DEGRADED


def test_compose_validity_empty_raises() -> None:
    """Llamada sin inputs es bug del caller (uncertainty.md §6)."""
    with pytest.raises(ValueError, match="al menos un input"):
        compose_validity()


@given(st.lists(validity_values, min_size=1, max_size=10))
def test_compose_validity_is_min_property(vs: list[Validity]) -> None:
    """Propiedad: el output es exactamente el mínimo sobre los inputs."""
    out = compose_validity(*vs)
    assert out == min(vs)


@given(st.lists(validity_values, min_size=1, max_size=8))
def test_compose_validity_no_silent_upgrade(vs: list[Validity]) -> None:
    """El output nunca supera a ningún input (sin upgrade silencioso, §6.1)."""
    out = compose_validity(*vs)
    for v in vs:
        assert out <= v


@given(st.lists(validity_values, min_size=2, max_size=8))
def test_compose_validity_is_associative(vs: list[Validity]) -> None:
    """Asociatividad: compose(a, compose(b, c)) == compose(compose(a, b), c)."""
    if len(vs) < 3:
        return
    a, b, c = vs[0], vs[1], vs[2]
    left = compose_validity(a, compose_validity(b, c))
    right = compose_validity(compose_validity(a, b), c)
    assert left == right


@given(st.lists(validity_values, min_size=2, max_size=8))
def test_compose_validity_is_commutative(vs: list[Validity]) -> None:
    """Conmutatividad: el orden de inputs no importa."""
    assert compose_validity(*vs) == compose_validity(*reversed(vs))
