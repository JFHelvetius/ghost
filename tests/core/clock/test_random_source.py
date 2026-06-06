"""Tests de `RandomSourceImpl` — determinismo jerárquico (T3, clock.md §4)."""

from __future__ import annotations

import numpy as np
import pytest

from project_ghost.core.clock import RandomSource, RandomSourceImpl

# ---------------------------------------------------------------------------
# Construcción e invariantes
# ---------------------------------------------------------------------------


def test_random_source_rejects_negative_seed() -> None:
    with pytest.raises(ValueError, match="seed"):
        RandomSourceImpl(seed=-1)


def test_random_source_accepts_zero_seed() -> None:
    rs = RandomSourceImpl(seed=0)
    assert rs.seed == 0
    assert rs.label == "/"


def test_random_source_rejects_label_without_leading_slash() -> None:
    with pytest.raises(ValueError, match="label"):
        RandomSourceImpl(seed=0, label="sensors")


def test_random_source_satisfies_protocol() -> None:
    rs = RandomSourceImpl(seed=42)
    assert isinstance(rs, RandomSource)


# ---------------------------------------------------------------------------
# Determinismo: misma seed + mismos labels -> misma secuencia
# ---------------------------------------------------------------------------


def test_random_source_deterministic_with_same_labels() -> None:
    rs1 = RandomSourceImpl(seed=42).child("sensors").child("imu0").child("noise")
    rs2 = RandomSourceImpl(seed=42).child("sensors").child("imu0").child("noise")
    seq1 = [rs1.uniform(0.0, 1.0) for _ in range(100)]
    seq2 = [rs2.uniform(0.0, 1.0) for _ in range(100)]
    assert seq1 == seq2


def test_different_seeds_produce_different_sequences() -> None:
    rs1 = RandomSourceImpl(seed=1).child("noise")
    rs2 = RandomSourceImpl(seed=2).child("noise")
    seq1 = [rs1.uniform(0.0, 1.0) for _ in range(20)]
    seq2 = [rs2.uniform(0.0, 1.0) for _ in range(20)]
    assert seq1 != seq2


def test_different_labels_produce_different_sequences() -> None:
    root = RandomSourceImpl(seed=42)
    rs_a = root.child("a")
    rs_b = root.child("b")
    seq_a = [rs_a.uniform(0.0, 1.0) for _ in range(20)]
    seq_b = [rs_b.uniform(0.0, 1.0) for _ in range(20)]
    assert seq_a != seq_b


def test_child_seed_is_stable_across_calls() -> None:
    """`root.child("x")` siempre devuelve un RandomSource con la misma seed."""
    root = RandomSourceImpl(seed=42)
    seeds = [root.child("noise").seed for _ in range(5)]
    assert len(set(seeds)) == 1


# ---------------------------------------------------------------------------
# Path label construction
# ---------------------------------------------------------------------------


def test_child_label_constructs_hierarchical_path() -> None:
    rs = RandomSourceImpl(seed=42).child("sensors").child("imu0").child("noise")
    assert rs.label == "/sensors/imu0/noise"


def test_child_label_normalizes_leading_slash() -> None:
    """`child("/imu0")` y `child("imu0")` producen el mismo label final."""
    a = RandomSourceImpl(seed=42).child("imu0")
    b = RandomSourceImpl(seed=42).child("/imu0")
    assert a.label == b.label == "/imu0"


def test_child_label_normalizes_leading_slash_produces_same_seed() -> None:
    """Una vez normalizado el segmento, el seed derivado es el mismo."""
    a = RandomSourceImpl(seed=42).child("imu0")
    b = RandomSourceImpl(seed=42).child("/imu0")
    assert a.seed == b.seed


def test_child_with_empty_label_raises() -> None:
    rs = RandomSourceImpl(seed=42)
    with pytest.raises(ValueError, match="vacío"):
        rs.child("")


def test_child_with_only_slashes_raises() -> None:
    rs = RandomSourceImpl(seed=42)
    with pytest.raises(ValueError, match="slashes"):
        rs.child("///")


# ---------------------------------------------------------------------------
# Distribuciones puente sobre numpy
# ---------------------------------------------------------------------------


def test_uniform_returns_float_in_range() -> None:
    rs = RandomSourceImpl(seed=42).child("u")
    for _ in range(50):
        x = rs.uniform(-1.0, 1.0)
        assert isinstance(x, float)
        assert -1.0 <= x <= 1.0


def test_normal_returns_float() -> None:
    rs = RandomSourceImpl(seed=42).child("n")
    for _ in range(50):
        x = rs.normal(0.0, 1.0)
        assert isinstance(x, float)


def test_integers_returns_int_in_range() -> None:
    rs = RandomSourceImpl(seed=42).child("i")
    for _ in range(50):
        x = rs.integers(10, 20)
        assert isinstance(x, int)
        assert 10 <= x < 20


def test_numpy_rng_returns_generator() -> None:
    rs = RandomSourceImpl(seed=42)
    rng = rs.numpy_rng()
    assert isinstance(rng, np.random.Generator)


def test_numpy_rng_returns_same_instance_on_repeated_calls() -> None:
    """Spec: llamadas sucesivas devuelven el mismo Generator dentro de
    la misma instancia. Para concerns independientes, crear `child()`."""
    rs = RandomSourceImpl(seed=42)
    assert rs.numpy_rng() is rs.numpy_rng()


def test_numpy_rng_state_advances_with_use() -> None:
    rs = RandomSourceImpl(seed=42)
    rng = rs.numpy_rng()
    a = rng.standard_normal(5).tolist()
    b = rng.standard_normal(5).tolist()
    assert a != b  # estado del generator avanzó
