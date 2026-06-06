"""Tests de los modelos de inflación de covarianza (uncertainty.md §5)."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from project_ghost.core.uncertainty import (
    inflate_directional,
    inflate_isotropic,
    inflate_stale,
)

from .strategies import alpha_floats, severity_floats, symmetric_psd_matrices

_HYPO_SETTINGS = settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=(HealthCheck.data_too_large,),
)

# ---------------------------------------------------------------------------
# §5.1 — Isotrópica
# ---------------------------------------------------------------------------


@given(symmetric_psd_matrices(n=3), alpha_floats)
@_HYPO_SETTINGS
def test_isotropic_inflation_recovers_nominal_at_zero_severity(C: np.ndarray, alpha: float) -> None:
    """uncertainty.md §5.1: severity=0 ⇒ C_eff == C_nominal."""
    inflated = inflate_isotropic(C, severity=0.0, alpha=alpha)
    np.testing.assert_array_equal(inflated, C)


@given(
    C=symmetric_psd_matrices(n=3),
    sev_low=st.floats(min_value=0.0, max_value=0.49, allow_nan=False, width=64),
    sev_high=st.floats(min_value=0.5, max_value=1.0, allow_nan=False, width=64),
    alpha=st.floats(min_value=0.1, max_value=5.0, allow_nan=False, width=64),
)
@_HYPO_SETTINGS
def test_isotropic_inflation_monotonic_in_severity(
    C: np.ndarray, sev_low: float, sev_high: float, alpha: float
) -> None:
    """Mayor severity ⇒ mayor norma de C_eff."""
    low = inflate_isotropic(C, severity=sev_low, alpha=alpha)
    high = inflate_isotropic(C, severity=sev_high, alpha=alpha)
    if float(np.linalg.norm(C, ord="fro")) > 0:
        assert float(np.linalg.norm(high, ord="fro")) >= float(np.linalg.norm(low, ord="fro"))


@given(symmetric_psd_matrices(n=3), severity_floats, alpha_floats)
@_HYPO_SETTINGS
def test_isotropic_inflation_preserves_psd(C: np.ndarray, severity: float, alpha: float) -> None:
    """C_eff sigue siendo PSD (factor ≥ 1, escalar; preserva eigenvalores)."""
    inflated = inflate_isotropic(C, severity=severity, alpha=alpha)
    min_eig = float(np.min(np.linalg.eigvalsh(0.5 * (inflated + inflated.T))))
    assert min_eig >= -1e-9


def test_isotropic_inflation_seals_output() -> None:
    C = np.eye(3, dtype=np.float64)
    out = inflate_isotropic(C, severity=0.5)
    assert not out.flags.writeable


def test_isotropic_inflation_clips_severity_to_range() -> None:
    """Severity > 1 se clipa a 1; < 0 se clipa a 0."""
    C = np.eye(3, dtype=np.float64)
    out_above = inflate_isotropic(C, severity=10.0, alpha=2.0)
    out_at_one = inflate_isotropic(C, severity=1.0, alpha=2.0)
    np.testing.assert_array_equal(out_above, out_at_one)
    out_below = inflate_isotropic(C, severity=-1.0, alpha=2.0)
    np.testing.assert_array_equal(out_below, C)


def test_isotropic_inflation_rejects_negative_alpha() -> None:
    with pytest.raises(ValueError, match="alpha"):
        inflate_isotropic(np.eye(3), severity=0.5, alpha=-0.1)


# ---------------------------------------------------------------------------
# §5.2 — Direccional
# ---------------------------------------------------------------------------


def test_directional_inflation_identity_rotation_scales_diagonal() -> None:
    """Con R=I y scales=(1,1,3), la inflación afecta el eje z principalmente."""
    C = np.eye(3, dtype=np.float64)
    R = np.eye(3, dtype=np.float64)
    scales = np.array([1.0, 1.0, 3.0], dtype=np.float64)
    out = inflate_directional(C, R, scales)
    # M = R S Rᵀ = diag(1, 1, 9). C_eff = M C M = diag(1, 1, 81).
    expected = np.diag([1.0, 1.0, 81.0])
    np.testing.assert_allclose(out, expected)


def test_directional_inflation_unit_scales_preserves_covariance() -> None:
    """scales=(1,1,1) deja C intacta tras inflación direccional."""
    C = np.array([[2.0, 0.5, 0.0], [0.5, 1.5, 0.0], [0.0, 0.0, 1.0]])
    R = np.eye(3, dtype=np.float64)
    out = inflate_directional(C, R, np.ones(3, dtype=np.float64))
    np.testing.assert_allclose(out, C)


def test_directional_inflation_seals_output() -> None:
    out = inflate_directional(np.eye(3, dtype=np.float64), np.eye(3, dtype=np.float64), np.ones(3))
    assert not out.flags.writeable


def test_directional_inflation_rejects_bad_shapes() -> None:
    with pytest.raises(ValueError, match="C debe ser"):
        inflate_directional(np.eye(2), np.eye(3), np.ones(3))
    with pytest.raises(ValueError, match="R_cam_world"):
        inflate_directional(np.eye(3), np.eye(2), np.ones(3))
    with pytest.raises(ValueError, match="scales"):
        inflate_directional(np.eye(3), np.eye(3), np.ones(4))


def test_directional_inflation_rejects_negative_scales() -> None:
    with pytest.raises(ValueError, match="scales"):
        inflate_directional(np.eye(3), np.eye(3), np.array([1.0, -1.0, 1.0]))


# ---------------------------------------------------------------------------
# §5.4 — Stale (dead reckoning)
# ---------------------------------------------------------------------------


@given(
    C=symmetric_psd_matrices(n=3),
    age_a=st.integers(min_value=0, max_value=10**12),
    age_b=st.integers(min_value=0, max_value=10**12),
)
@_HYPO_SETTINGS
def test_stale_inflation_monotonic_in_age(C: np.ndarray, age_a: int, age_b: int) -> None:
    """uncertainty.md §5.4: mayor edad ⇒ mayor norma de C_eff (Q_dr ≻ 0)."""
    Q = np.eye(3, dtype=np.float64)  # Q_dr ≻ 0 estricto.
    young, old = sorted((age_a, age_b))
    cov_young = inflate_stale(C, age_ns=young, Q_dr=Q)
    cov_old = inflate_stale(C, age_ns=old, Q_dr=Q)
    # trace es monótono en la suma con Q definido positivo.
    assert float(np.trace(cov_old)) >= float(np.trace(cov_young)) - 1e-12


def test_stale_inflation_zero_age_returns_nominal() -> None:
    C = np.eye(3, dtype=np.float64)
    Q = np.eye(3, dtype=np.float64)
    out = inflate_stale(C, age_ns=0, Q_dr=Q)
    np.testing.assert_array_equal(out, C)


def test_stale_inflation_seals_output() -> None:
    out = inflate_stale(np.eye(3), age_ns=10**9, Q_dr=np.eye(3, dtype=np.float64))
    assert not out.flags.writeable


def test_stale_inflation_rejects_negative_age() -> None:
    with pytest.raises(ValueError, match="age_ns"):
        inflate_stale(np.eye(3), age_ns=-1, Q_dr=np.eye(3, dtype=np.float64))


def test_stale_inflation_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="shape"):
        inflate_stale(np.eye(3), age_ns=0, Q_dr=np.eye(4, dtype=np.float64))


def test_stale_inflation_unit_q_at_one_second_adds_identity() -> None:
    """En t=1s con Q=I, C_eff = C + I."""
    C = 2.0 * np.eye(3, dtype=np.float64)
    Q = np.eye(3, dtype=np.float64)
    out = inflate_stale(C, age_ns=10**9, Q_dr=Q)
    expected = C + Q
    np.testing.assert_allclose(out, expected)
