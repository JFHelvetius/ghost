"""Tests de `Estimate[T]` y `make_estimate`.

Cubre los invariantes obligatorios de `uncertainty.md` §3 y los tests
del §11 alcanzables sin detector ni event bus:

- ``test_estimate_rejects_asymmetric_covariance`` (§3.3)
- ``test_estimate_rejects_non_psd_covariance`` (§3.4)
- ``test_estimate_seals_arrays_recursively`` (§3.2)
- ``test_estimate_rejects_validity_covariance_inconsistency`` (§3.10)
- ``test_groundtruth_iff_covariance_none`` (§3.8)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings

from project_ghost.core.uncertainty import (
    Estimate,
    EstimateSource,
    NominalEnvelope,
    Validity,
    make_estimate,
)

from .strategies import (
    asymmetric_matrices,
    non_psd_matrices,
    symmetric_psd_matrices,
    validity_values,
)

# Hypothesis HealthCheck: las estrategias compuestas son pesadas; subimos
# el deadline y deshabilitamos data_too_large en los tests más caros.
_HYPO_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=(HealthCheck.data_too_large,),
)


def _src(kind: str = "filter", module_id: str = "test.mod") -> EstimateSource:
    return EstimateSource(module_id=module_id, kind=kind, schema_version=1)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# §3.3 — Covarianza simétrica
# ---------------------------------------------------------------------------


@given(asymmetric_matrices(n=3))
@_HYPO_SETTINGS
def test_estimate_rejects_asymmetric_covariance(C: np.ndarray) -> None:
    """uncertainty.md §3.3."""
    with pytest.raises(ValueError, match="asimétrica"):
        Estimate(
            value=np.zeros(3),
            covariance=C,
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(),
        )


def test_estimate_symmetrizes_within_tolerance() -> None:
    """Asimetría minúscula (< 1e-9 relativo) se simetriza, no se rechaza."""
    C = np.array(
        [[1.0, 0.5, 0.0], [0.5 + 1e-15, 1.0, 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    est = Estimate(
        value=np.zeros(3),
        covariance=C,
        validity=Validity.VALID,
        stamp_sim_ns=0,
        source=_src(),
    )
    # Tras simetrización, |C - Cᵀ| es exactamente cero.
    assert est.covariance is not None
    assert np.allclose(est.covariance, est.covariance.T)


# ---------------------------------------------------------------------------
# §3.4 — Covarianza PSD
# ---------------------------------------------------------------------------


@given(non_psd_matrices(n=3))
@_HYPO_SETTINGS
def test_estimate_rejects_non_psd_covariance(C: np.ndarray) -> None:
    """uncertainty.md §3.4."""
    with pytest.raises(ValueError, match="PSD"):
        Estimate(
            value=np.zeros(3),
            covariance=C,
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(),
        )


@given(symmetric_psd_matrices(n=3))
@_HYPO_SETTINGS
def test_estimate_accepts_symmetric_psd_covariance(C: np.ndarray) -> None:
    est = Estimate(
        value=np.zeros(3),
        covariance=C,
        validity=Validity.VALID,
        stamp_sim_ns=0,
        source=_src(),
    )
    assert est.covariance is not None
    assert est.covariance.shape == (3, 3)


def test_estimate_rejects_wrong_dtype() -> None:
    C = np.eye(3, dtype=np.float32)
    with pytest.raises(ValueError, match="float64"):
        Estimate(
            value=np.zeros(3),
            covariance=C,
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(),
        )


def test_estimate_rejects_non_square_covariance() -> None:
    C = np.zeros((3, 4), dtype=np.float64)
    with pytest.raises(ValueError, match="cuadrada"):
        Estimate(
            value=np.zeros(3),
            covariance=C,
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(),
        )


# ---------------------------------------------------------------------------
# §3.8 — Groundtruth iff covariance None
# ---------------------------------------------------------------------------


def test_groundtruth_iff_covariance_none() -> None:
    """uncertainty.md §3.8."""
    # GT con covariance None → OK.
    Estimate(
        value=np.zeros(3),
        covariance=None,
        validity=Validity.VALID,
        stamp_sim_ns=0,
        source=_src(kind="groundtruth"),
    )
    # GT con covariance no-None → rechazo.
    with pytest.raises(ValueError, match="groundtruth"):
        Estimate(
            value=np.zeros(3),
            covariance=np.eye(3),
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(kind="groundtruth"),
        )
    # No-GT con covariance None → rechazo.
    with pytest.raises(ValueError, match="groundtruth"):
        Estimate(
            value=np.zeros(3),
            covariance=None,
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(kind="filter"),
        )


# ---------------------------------------------------------------------------
# §3.2 — Sealing recursivo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _NestedValue:
    """Dataclass de prueba que envuelve dos arrays mutables al construir."""

    position: np.ndarray
    orientation: np.ndarray


def test_estimate_seals_arrays_recursively() -> None:
    """uncertainty.md §3.2.

    El array dentro de `value` (dataclass) debe quedar read-only tras
    `make_estimate`.
    """
    pos = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    ori = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    assert pos.flags.writeable
    assert ori.flags.writeable

    est = make_estimate(
        value=_NestedValue(position=pos, orientation=ori),
        covariance=np.eye(3),
        validity=Validity.VALID,
        stamp_sim_ns=0,
        source=_src(),
    )

    assert not est.value.position.flags.writeable
    assert not est.value.orientation.flags.writeable
    assert est.covariance is not None
    assert not est.covariance.flags.writeable


def test_make_estimate_rejects_unstable_collection_in_value() -> None:
    """Sealing recursivo encuentra `set` y aborta (uncertainty.md §10)."""

    @dataclass(frozen=True)
    class WithSet:
        bag: frozenset[int]

    with pytest.raises(TypeError, match="inestable"):
        make_estimate(
            value=WithSet(bag=frozenset({1, 2, 3})),
            covariance=np.eye(3),
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(),
        )


# ---------------------------------------------------------------------------
# §3.10 — Consistencia validity↔covariance
# ---------------------------------------------------------------------------


def _envelope(scale: float = 1.0) -> NominalEnvelope:
    return NominalEnvelope(
        max_diag=np.array([scale, scale, scale]),
        max_trace=3.0 * scale,
    )


def test_estimate_rejects_validity_covariance_inconsistency_valid_inflated() -> None:
    """VALID con covarianza fuera de envelope → rechazo (§3.10)."""
    env = _envelope(scale=1.0)
    inflated = 100.0 * np.eye(3, dtype=np.float64)  # claramente fuera
    with pytest.raises(ValueError, match="VALID"):
        make_estimate(
            value=np.zeros(3),
            covariance=inflated,
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(),
            nominal_envelope=env,
        )


def test_estimate_rejects_validity_covariance_inconsistency_degraded_nominal() -> None:
    """DEGRADED con covarianza dentro de envelope → rechazo (§3.10)."""
    env = _envelope(scale=1.0)
    nominal = 0.1 * np.eye(3, dtype=np.float64)  # claramente dentro
    with pytest.raises(ValueError, match="DEGRADED"):
        make_estimate(
            value=np.zeros(3),
            covariance=nominal,
            validity=Validity.DEGRADED,
            stamp_sim_ns=0,
            source=_src(),
            nominal_envelope=env,
        )


def test_estimate_rejects_stale_with_nominal_covariance() -> None:
    env = _envelope(scale=1.0)
    nominal = 0.1 * np.eye(3, dtype=np.float64)
    with pytest.raises(ValueError, match="STALE"):
        make_estimate(
            value=np.zeros(3),
            covariance=nominal,
            validity=Validity.STALE,
            stamp_sim_ns=0,
            source=_src(),
            nominal_envelope=env,
        )


def test_estimate_accepts_invalid_regardless_of_covariance() -> None:
    """INVALID no se comprueba contra envelope; el valor no se usa."""
    env = _envelope(scale=1.0)
    # Tanto dentro como fuera del envelope son válidos cuando validity==INVALID.
    for cov in (0.1 * np.eye(3), 100.0 * np.eye(3)):
        make_estimate(
            value=np.zeros(3),
            covariance=np.asarray(cov, dtype=np.float64),
            validity=Validity.INVALID,
            stamp_sim_ns=0,
            source=_src(),
            nominal_envelope=env,
        )


def test_make_estimate_accepts_valid_within_envelope() -> None:
    env = _envelope(scale=1.0)
    nominal = 0.1 * np.eye(3, dtype=np.float64)
    est = make_estimate(
        value=np.zeros(3),
        covariance=nominal,
        validity=Validity.VALID,
        stamp_sim_ns=0,
        source=_src(),
        nominal_envelope=env,
    )
    assert est.validity == Validity.VALID


def test_make_estimate_without_envelope_skips_consistency_check() -> None:
    """Sin envelope, el constructor solo aplica checks estructurales."""
    cov = 100.0 * np.eye(3, dtype=np.float64)
    est = make_estimate(
        value=np.zeros(3),
        covariance=cov,
        validity=Validity.VALID,
        stamp_sim_ns=0,
        source=_src(),
    )
    assert est.validity == Validity.VALID


# ---------------------------------------------------------------------------
# Otros checks estructurales
# ---------------------------------------------------------------------------


def test_estimate_rejects_negative_stamp() -> None:
    with pytest.raises(ValueError, match="stamp_sim_ns"):
        Estimate(
            value=np.zeros(3),
            covariance=np.eye(3),
            validity=Validity.VALID,
            stamp_sim_ns=-1,
            source=_src(),
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1, 2.0])
def test_estimate_rejects_confidence_out_of_range(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        Estimate(
            value=np.zeros(3),
            covariance=np.eye(3),
            validity=Validity.VALID,
            stamp_sim_ns=0,
            source=_src(),
            confidence=confidence,
        )


@given(validity_values)
def test_estimate_accepts_any_validity_with_consistent_covariance(v: Validity) -> None:
    """Sin envelope, cualquier validity es admisible."""
    # VALID con cov nominal; otros validity con cualquier PSD (no se valida sin envelope).
    cov = np.eye(3, dtype=np.float64) if v == Validity.VALID else 5.0 * np.eye(3, dtype=np.float64)
    est = make_estimate(
        value=np.zeros(3),
        covariance=cov,
        validity=v,
        stamp_sim_ns=0,
        source=_src(),
    )
    assert est.validity == v


def test_estimate_seals_covariance_after_construction() -> None:
    """Verificación directa: la covarianza queda read-only tras make_estimate."""
    cov = np.eye(3, dtype=np.float64)
    est = make_estimate(
        value=np.zeros(3),
        covariance=cov,
        validity=Validity.VALID,
        stamp_sim_ns=0,
        source=_src(),
    )
    assert est.covariance is not None
    assert not est.covariance.flags.writeable
    with pytest.raises(ValueError, match=r"read-only|read.only|assignment destination"):
        est.covariance[0, 0] = 99.0
