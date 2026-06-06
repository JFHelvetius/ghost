"""Tests de los tipos congelados de `core.uncertainty`.

Cubre invariantes simples de las dataclasses/enums sin lógica matemática
adicional. La lógica de `Estimate` se prueba en `test_estimate.py`.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest
from hypothesis import given

from project_ghost.core.uncertainty import (
    EstimateSource,
    NominalEnvelope,
    PerceptionMode,
    Validity,
)

from .strategies import diagonal_psd_matrices

# ---------------------------------------------------------------------------
# Validity (uncertainty.md §2)
# ---------------------------------------------------------------------------


def test_validity_total_order() -> None:
    """VALID > DEGRADED > STALE > INVALID (mayor = mejor)."""
    assert Validity.VALID > Validity.DEGRADED
    assert Validity.DEGRADED > Validity.STALE
    assert Validity.STALE > Validity.INVALID


def test_validity_min_is_most_restrictive() -> None:
    """Composición = min sobre IntEnum devuelve el peor."""
    assert min(Validity.VALID, Validity.DEGRADED) == Validity.DEGRADED
    assert min(Validity.STALE, Validity.INVALID) == Validity.INVALID
    assert min(Validity.VALID, Validity.VALID) == Validity.VALID


# ---------------------------------------------------------------------------
# PerceptionMode (uncertainty.md §2 + ADR-0010)
# ---------------------------------------------------------------------------


def test_perception_mode_catalog_has_exactly_eight_modes() -> None:
    """ADR-0008 fijó 7; ADR-0010 añadió MOTION_AGGRESSIVE → 8."""
    assert len(list(PerceptionMode)) == 8


def test_perception_mode_includes_motion_aggressive() -> None:
    """ADR-0010 §1."""
    assert PerceptionMode.MOTION_AGGRESSIVE in set(PerceptionMode)


def test_perception_mode_str_values_stable() -> None:
    """Los string values son contrato; cambiar uno requiere ADR (uncertainty.md §10)."""
    expected = {
        "nominal",
        "low_texture",
        "low_light",
        "imu_saturation",
        "vio_lost",
        "map_ambiguous",
        "motion_aggressive",
        "perception_dead",
    }
    assert {m.value for m in PerceptionMode} == expected


# ---------------------------------------------------------------------------
# EstimateSource
# ---------------------------------------------------------------------------


def test_estimate_source_rejects_invalid_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        EstimateSource(module_id="x", kind="bogus", schema_version=1)  # type: ignore[arg-type]


def test_estimate_source_rejects_empty_module_id() -> None:
    with pytest.raises(ValueError, match="module_id"):
        EstimateSource(module_id="", kind="filter", schema_version=1)


def test_estimate_source_rejects_zero_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        EstimateSource(module_id="vo.front", kind="vo", schema_version=0)


def test_estimate_source_accepts_all_documented_kinds() -> None:
    """Todos los kinds documentados en uncertainty.md §2 deben construir."""
    for k in ("sensor", "filter", "vo", "slam", "groundtruth", "fused"):
        src = EstimateSource(module_id="m", kind=k, schema_version=1)
        assert src.kind == k


def test_estimate_source_is_frozen() -> None:
    src = EstimateSource(module_id="m", kind="filter", schema_version=1)
    with pytest.raises(FrozenInstanceError):
        src.module_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NominalEnvelope
# ---------------------------------------------------------------------------


def test_nominal_envelope_rejects_non_positive_diag() -> None:
    with pytest.raises(ValueError, match="max_diag"):
        NominalEnvelope(max_diag=np.array([1.0, 0.0, 1.0]), max_trace=10.0)


def test_nominal_envelope_rejects_non_positive_trace() -> None:
    with pytest.raises(ValueError, match="max_trace"):
        NominalEnvelope(max_diag=np.array([1.0, 1.0, 1.0]), max_trace=0.0)


def test_nominal_envelope_seals_max_diag() -> None:
    env = NominalEnvelope(max_diag=np.array([1.0, 2.0, 3.0]), max_trace=10.0)
    assert not env.max_diag.flags.writeable


@given(diagonal_psd_matrices(n=3))
def test_nominal_envelope_contains_handles_diagonal(C: np.ndarray) -> None:
    """contains() es coherente: una diagonal con diag ≤ max_diag y trace ≤ max_trace está dentro."""
    env = NominalEnvelope(
        max_diag=np.array([1e6, 1e6, 1e6]),
        max_trace=1e9,
    )
    # Para C diagonal positiva pequeña, ambos criterios se cumplen.
    if float(np.trace(C)) <= 1e9 and np.all(np.diag(C) <= 1e6):
        assert env.contains(C)
