"""Tests del módulo de sealing recursivo.

Cubre los caminos que `test_estimate.py` no toca directamente:

- Traversal en ``tuple`` y ``list`` (secuencias estables).
- Rechazo de ``set`` / ``frozenset`` / ``dict`` en `seal_recursive`.
- ``assert_all_sealed`` detectando un ``ndarray`` aún escribible.
- ``assert_all_sealed`` detectando una colección inestable.
- Tipos escalares y `None` (no-op silencioso).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from project_ghost.core.uncertainty.sealing import (
    assert_all_sealed,
    seal_recursive,
)

# ---------------------------------------------------------------------------
# seal_recursive — tuple / list
# ---------------------------------------------------------------------------


def test_seal_recursive_seals_tuple_of_arrays() -> None:
    a = np.array([1.0, 2.0])
    b = np.array([3.0, 4.0])
    seal_recursive((a, b))
    assert not a.flags.writeable
    assert not b.flags.writeable


def test_seal_recursive_seals_list_of_arrays() -> None:
    a = np.array([1.0, 2.0])
    b = np.array([3.0, 4.0])
    seal_recursive([a, b])
    assert not a.flags.writeable
    assert not b.flags.writeable


def test_seal_recursive_seals_nested_tuple_in_dataclass() -> None:
    @dataclass(frozen=True)
    class Bundle:
        arrays: tuple[np.ndarray, np.ndarray]

    a = np.array([1.0, 2.0])
    b = np.array([3.0, 4.0])
    seal_recursive(Bundle(arrays=(a, b)))
    assert not a.flags.writeable
    assert not b.flags.writeable


# ---------------------------------------------------------------------------
# seal_recursive — colecciones inestables (uncertainty.md §10)
# ---------------------------------------------------------------------------


def test_seal_recursive_rejects_set() -> None:
    with pytest.raises(TypeError, match="inestable"):
        seal_recursive({1, 2, 3})


def test_seal_recursive_rejects_frozenset() -> None:
    with pytest.raises(TypeError, match="inestable"):
        seal_recursive(frozenset({1, 2, 3}))


def test_seal_recursive_rejects_dict() -> None:
    with pytest.raises(TypeError, match="inestable"):
        seal_recursive({"k": 1})


def test_seal_recursive_rejects_set_inside_dataclass() -> None:
    @dataclass(frozen=True)
    class Bad:
        bag: set[int]

    with pytest.raises(TypeError, match="inestable"):
        seal_recursive(Bad(bag={1, 2}))


# ---------------------------------------------------------------------------
# seal_recursive — tipos escalares y None (no-op)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scalar", [0, 1.5, "x", b"y", None, True, (1, 2, 3)])
def test_seal_recursive_noop_on_scalars(scalar: object) -> None:
    """Tipos sin arrays son no-op silenciosa."""
    seal_recursive(scalar)


# ---------------------------------------------------------------------------
# assert_all_sealed — detección de fallos
# ---------------------------------------------------------------------------


def test_assert_all_sealed_passes_when_arrays_sealed() -> None:
    a = np.array([1.0, 2.0])
    a.flags.writeable = False
    assert_all_sealed(a)


def test_assert_all_sealed_raises_on_writeable_array() -> None:
    a = np.array([1.0, 2.0])
    assert a.flags.writeable
    with pytest.raises(ValueError, match="escribible"):
        assert_all_sealed(a)


def test_assert_all_sealed_reports_path_in_dataclass() -> None:
    @dataclass(frozen=True)
    class Holder:
        position: np.ndarray

    bad = Holder(position=np.array([1.0, 2.0]))  # no sellado
    with pytest.raises(ValueError, match=r"position"):
        assert_all_sealed(bad)


def test_assert_all_sealed_reports_path_in_tuple() -> None:
    a = np.array([1.0, 2.0])  # no sellado
    with pytest.raises(ValueError, match=r"\[0\]"):
        assert_all_sealed((a,))


def test_assert_all_sealed_rejects_unstable_collection_at_root() -> None:
    with pytest.raises(TypeError, match="inestable"):
        assert_all_sealed({1, 2})


def test_assert_all_sealed_rejects_unstable_collection_in_dataclass() -> None:
    @dataclass(frozen=True)
    class Holder:
        bag: frozenset[int]

    with pytest.raises(TypeError, match="inestable"):
        assert_all_sealed(Holder(bag=frozenset({1})))


def test_assert_all_sealed_noop_on_scalars() -> None:
    assert_all_sealed(42)
    assert_all_sealed("ok")
    assert_all_sealed(None)
